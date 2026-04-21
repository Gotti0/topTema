import asyncio
import logging
import orjson
import aiohttp
import time
from typing import Callable, Any, Dict, List, Optional, Set

from config.settings import WS_DOMAIN, ACCOUNTS
from core.auth import TokenManager
from core.exceptions import WebSocketLoginError, WebSocketConnectionError
from core.constants import FID_0B, FID_0C

logger = logging.getLogger(__name__)

class KiwoomWebSocketClient:
    """
    키움증권 실시간 웹소켓(WebSocket) 클라이언트입니다.
    공식 API 명세에 따라 LOGIN → REG(구독) → REAL(실시간 수신) → PING(에코백) 프로토콜을 구현합니다.
    수신되는 대량의 틱(Tick) 및 호가 데이터를 asyncio.Queue에 버퍼링하고,
    백그라운드 워커에서 순차적으로 처리하여 시스템 과부하를 방지합니다.

    [강건성 향상: 적응형 샘플링]
    구독 종목 수가 많아질수록 개별 종목의 데이터 처리 간격을 늘려 시스템 안정성을 확보합니다.
    """
    def __init__(self, ws_url: str = WS_DOMAIN, token_manager: Optional[TokenManager] = None):
        self.ws_url = ws_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.msg_queue = asyncio.Queue()
        self._listen_task: Optional[asyncio.Task] = None
        self._worker_task: Optional[asyncio.Task] = None
        self.token_manager = token_manager or TokenManager()
        self.on_message_callback: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._is_running = False

        # 샘플링 및 통계 관련 상태 변수
        self._subscribed_symbols: Set[str] = set()
        self._last_processed_times: Dict[str, float] = {}
        self._min_interval: float = 0.0 
        
        # 통계용 카운터
        self.stats = {
            "total_recv": 0,
            "total_proc": 0,
            "start_time": time.time()
        }

    def get_stats(self):
        """현재까지의 수신 통계를 반환하고 카운터를 초기화할 수 있습니다."""
        now = time.time()
        duration = now - self.stats["start_time"]
        report = {
            "duration_sec": duration,
            "total_recv": self.stats["total_recv"],
            "total_proc": self.stats["total_proc"],
            "skip_rate": (1 - self.stats["total_proc"] / self.stats["total_recv"]) * 100 if self.stats["total_recv"] > 0 else 0
        }
        # 다음 주기를 위해 초기화 (선택 사항, 호출부에서 결정)
        return report

    def reset_stats(self):
        self.stats["total_recv"] = 0
        self.stats["total_proc"] = 0
        self.stats["start_time"] = time.time()

    def _update_sampling_config(self):
        """구독된 종목 수와 상관없이 사용자 요청에 따라 3초 강제 샘플링 간격을 설정합니다."""
        self._min_interval = 3.0
        logger.info(f"샘플링 설정 완료: 모든 종목 최소 처리 간격={self._min_interval:.2f}s")

    async def connect(self):
        """웹소켓 서버에 연결하고 LOGIN 인증 후 수신/워커 루프를 시작합니다."""
        self._is_running = True
        self.session = aiohttp.ClientSession()

        try:
            self.ws = await self.session.ws_connect(self.ws_url, heartbeat=30)
            logger.info("키움증권 WebSocket 연결에 성공했습니다.")

            # LOGIN 패킷 전송 (API 명세 필수)
            await self._login()

            self._listen_task = asyncio.create_task(self._listen())
            self._worker_task = asyncio.create_task(self._process_queue())
        except Exception as e:
            logger.error(f"WebSocket 연결/로그인 실패: {e}")
            if self.session:
                await self.session.close()
                self.session = None
            raise

    async def _login(self):
        """연결 직후 LOGIN 패킷을 전송하고 서버 응답을 확인합니다."""
        account_no = ACCOUNTS[0] if ACCOUNTS else None
        if not account_no:
             raise WebSocketLoginError("LOGIN 실패: 설정된 계좌번호(ACCOUNTS)가 없습니다.")

        token = await self.token_manager.get_token(account_no)
        logger.info(f"WebSocket 로그인 시도 중... 토큰 획득 결과: {'성공' if token else '실패'}")
        if not token:
            raise WebSocketLoginError(f"LOGIN 실패: 계좌 {account_no}에 대한 유효한 토큰이 없습니다.")

        login_packet = {
            "trnm": "LOGIN",
            "token": token
        }
        logger.debug(f"LOGIN 패킷 전송: {orjson.dumps(login_packet).decode('utf-8')}")
        await self.ws.send_json(login_packet)

        # LOGIN 응답 대기
        try:
            resp = await asyncio.wait_for(self.ws.receive_json(), timeout=10)
            logger.debug(f"LOGIN 응답 수신: {resp}")

            if resp.get("trnm") == "LOGIN" and resp.get("return_code") == 0:
                logger.info("WebSocket LOGIN 인증 성공.")
            else:
                err_msg = resp.get("return_msg", "알 수 없는 오류")
                err_code = resp.get("return_code")
                raise WebSocketLoginError(
                    f"LOGIN 실패: return_code={err_code}, msg={err_msg}",
                    return_code=err_code,
                    return_msg=err_msg,
                )
        except asyncio.TimeoutError:
            raise WebSocketLoginError(
                "LOGIN 실패: 서버 응답 시간 초과 (10초)",
                return_code=None,
                return_msg="timeout",
            )

    async def register(self, stk_cd_list: List[str], type_list: List[str], grp_no: str = "1", refresh: str = "1"):
        """
        실시간 데이터 구독을 등록합니다 (API 명세 REG).
        입력받은 종목 리스트가 100개를 초과할 경우, API 명세에 따라 100개씩 나누어 전송합니다.
        """
        if not self.ws or self.ws.closed:
            logger.warning(f"WebSocket이 닫혀 있어 구독(REG)을 보류합니다. 재연결 시 자동으로 구독됩니다.")
            return

        # 구독 상태 업데이트
        if refresh == "0":
            self._subscribed_symbols = set(stk_cd_list)
        else:
            self._subscribed_symbols.update(stk_cd_list)
        
        self._update_sampling_config()

        # 100개 단위로 Chunking 처리
        chunk_size = 100
        for i in range(0, len(stk_cd_list), chunk_size):
            chunk = stk_cd_list[i:i + chunk_size]
            current_refresh = refresh
            if i > 0 and refresh == "0":
                current_refresh = "1"

            payload = {
                "trnm": "REG",
                "grp_no": grp_no,
                "refresh": current_refresh,
                "data": [{
                    "item": chunk,
                    "type": type_list
                }]
            }
            try:
                await self.ws.send_str(orjson.dumps(payload).decode('utf-8'))
                logger.info(f"실시간 데이터 구독 요청 전송 완료: items_count={len(chunk)}, types={type_list}, refresh={current_refresh}")
                if i + chunk_size < len(stk_cd_list):
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"실시간 데이터 구독(REG) 중 에러 (배치 {i//chunk_size + 1}): {e}")
                raise

    async def unregister(self, stk_cd_list: List[str], type_list: List[str], grp_no: str = "1"):
        """
        실시간 데이터 구독을 해제합니다 (API 명세 REMOVE).
        """
        if not self.ws or self.ws.closed:
            logger.warning("WebSocket이 닫혀 있어 구독 해제(REMOVE)를 보류합니다.")
            return

        for cd in stk_cd_list:
            self._subscribed_symbols.discard(cd)
            self._last_processed_times.pop(cd, None)
        
        self._update_sampling_config()

        chunk_size = 100
        for i in range(0, len(stk_cd_list), chunk_size):
            chunk = stk_cd_list[i:i + chunk_size]
            payload = {
                "trnm": "REMOVE",
                "grp_no": grp_no,
                "data": [{
                    "item": chunk,
                    "type": type_list
                }]
            }
            try:
                await self.ws.send_str(orjson.dumps(payload).decode('utf-8'))
                logger.info(f"실시간 데이터 구독 해제 전송 완료: items_count={len(chunk)}, types={type_list}")
                if i + chunk_size < len(stk_cd_list):
                    await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"실시간 데이터 구독 해제(REMOVE) 중 에러 (배치 {i//chunk_size + 1}): {e}")

    async def subscribe(self, tr_cd: str, tr_key: str):
        await self.register(stk_cd_list=[tr_key], type_list=[tr_cd])

    def parse_market_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        raw FID 데이터를 constants.py에 정의된 필드명으로 변환합니다.
        """
        trnm = data.get("trnm")
        if trnm != "REAL":
            return data

        parsed_data = {
            "trnm": "REAL",
            "key": data.get("key"),
            "data": []
        }

        for entry in data.get("data", []):
            msg_type = entry.get("type")
            item = entry.get("item")
            values = entry.get("values", {})
            
            fid_map = {}
            if msg_type == "0B":
                fid_map = FID_0B
            elif msg_type == "0C":
                fid_map = FID_0C
            elif msg_type == "00":
                fid_map = FID_00
            elif msg_type == "04":
                fid_map = FID_04
            
            if fid_map:
                mapped_values = {}
                for fid, val in values.items():
                    field_name = fid_map.get(fid, fid)
                    mapped_values[field_name] = val
                
                parsed_data["data"].append({
                    "type": msg_type,
                    "item": item,
                    "values": mapped_values
                })
            else:
                parsed_data["data"].append(entry)
                
        return parsed_data

    async def _listen(self):
        """수신되는 메시지를 분류하여 PING은 에코백, REAL 데이터는 Queue에 담습니다."""
        if not self.ws:
            return

        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = orjson.loads(msg.data)
                        trnm = data.get("trnm", "")

                        if trnm == "PING":
                            await self.ws.send_str(orjson.dumps(data).decode('utf-8'))
                            continue

                        if trnm in ("REG", "REMOVE", "LOGIN"):
                            rc = data.get("return_code", -1)
                            rm = data.get("return_msg", "")
                            if rc == 0:
                                logger.info(f"[{trnm}] 서버 응답 정상 (return_code=0)")
                            else:
                                logger.warning(f"[{trnm}] 서버 응답 오류: code={rc}, msg={rm}")
                            continue

                        if trnm == "REAL":
                            self.stats["total_recv"] += 1
                            stk_cd = data.get("key")
                            if not stk_cd and data.get("data"):
                                stk_cd = data.get("data")[0].get("item")
                                
                            now = time.time()
                            last_time = self._last_processed_times.get(stk_cd, 0.0)
                            if (now - last_time) >= self._min_interval:
                                await self.msg_queue.put(data)
                                self.stats["total_proc"] += 1
                                if stk_cd:
                                    self._last_processed_times[stk_cd] = now
                            continue

                        await self.msg_queue.put(data)

                    except Exception as e:
                        logger.error(f"메시지 파싱 에러: {e}, raw={str(msg.data)[:200]}")
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    logger.warning(f"웹소켓 연결이 종료되었습니다. type={msg.type}")
                    break
        except Exception as e:
            logger.warning(f"웹소켓 수신 중 예외 발생: {e}")

    async def _process_queue(self):
        """버퍼링된 Queue에서 메시지를 하나씩 꺼내어 파싱 후 콜백으로 넘깁니다."""
        while self._is_running:
            try:
                data = await self.msg_queue.get()
                
                # 데이터 파싱 고도화
                if data.get("trnm") == "REAL":
                    data = self.parse_market_data(data)

                if self.on_message_callback:
                    if asyncio.iscoroutinefunction(self.on_message_callback):
                        await self.on_message_callback(data)
                    else:
                        self.on_message_callback(data)

                self.msg_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"메시지 처리 워커 에러: {e}")

    async def close(self):
        """모든 연결과 루프를 안전하게 종료합니다."""
        self._is_running = False
        if self._listen_task:
            self._listen_task.cancel()
        if self._worker_task:
            self._worker_task.cancel()
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()
        logger.info("키움증권 WebSocket 연결이 종료되었습니다.")
