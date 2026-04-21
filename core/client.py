import aiohttp
import asyncio
import time
import logging
import random
from typing import Dict, Any, Optional, Union

from config.settings import API_DOMAIN, ACCOUNTS
from core.backoff import BackoffWaiter, ExponentialBackoffWaiter
from core.exceptions import KiwoomAPIError, TokenExpiredError, RateLimitExceededError
from core.auth import TokenManager
from core.throttler import throttler

logger = logging.getLogger(__name__)

class KiwoomRestClient:
    """
    Asynchronous client wrapper for Kiwoom REST API.
    Handles automatic header injection, OAuth token management, and error wrapping.
    """
    
    def __init__(self, app_key: str, secret_key: str, token_manager: Optional[TokenManager] = None):
        if not app_key or not secret_key:
            logger.warning("APP_KEY or SECRET_KEY is missing. Please check your .env settings.")
            
        self.app_key = app_key
        self.secret_key = secret_key
        self.base_url = API_DOMAIN
        self.token_manager = token_manager or TokenManager()
        self.session: Optional[aiohttp.ClientSession] = None
        self.max_rate_limit_retries = 5
        self.rate_limit_backoff_waiter: BackoffWaiter = ExponentialBackoffWaiter(
            base_delay=1.0,
            max_delay=30.0,
            jitter_ratio=0.5,  # 지터 추가
            sleep_fn=asyncio.sleep,
            random_fn=random.uniform,
        )
        # GlobalThrottler가 전역 및 계좌별 실질적 속도 제한을 담당하므로 
        # 세마포어는 동시 네트워크 커넥션 수(초 저수준) 제어용도로만 유지 또는 확장 고려.
        self._request_semaphore = asyncio.Semaphore(10) 

    async def __aenter__(self):
        """Async context manager entry: initiates the aiohttp session."""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit: gracefully closes the session."""
        if self.session:
            await self.session.close()

    async def _request(self, method: str, endpoint: str, 
                       api_id: str, 
                       payload: Optional[Dict] = None, 
                       require_auth: bool = True,
                       cont_yn: str = "N",
                       next_key: str = "",
                       auth_retry_allowed: bool = True) -> Dict[str, Any]:
        """
        Generic HTTP request constructor with Exponential Backoff and Concurrency Limiting.
        """
        async with self._request_semaphore:
            # [Global Throttling] 토큰 버킷 알고리즘 적용
            # 페이로드에서 계좌번호 추출하여 계좌별 쿼터 소진
            acnt_no = (payload or {}).get("acnt_no")
            await throttler.consume(acnt_no)

            if not self.session:
                raise RuntimeError("ClientSession not initialized. Use 'async with KiwoomRestClient() as client:'")
                
            url = f"{self.base_url}{endpoint}"
            headers = {
                "api-id": api_id,
                "Content-Type": "application/json;charset=UTF-8"
            }
            
            # Paging flags
            if cont_yn == "Y" and next_key:
                headers["cont-yn"] = cont_yn
                headers["next-key"] = next_key

            max_retries = self.max_rate_limit_retries
            token_refreshed = False
            unauthorized_retried = False
            
            for attempt in range(max_retries):
                if require_auth:
                    # acnt_no가 있으면 해당 계좌의 토큰을, 없으면 첫 번째 계좌의 토큰을 가져옴
                    target_acnt = acnt_no or (ACCOUNTS[0] if ACCOUNTS else None)
                    if not target_acnt:
                        raise ValueError("No account number provided and ACCOUNTS in settings is empty.")
                    
                    token = await self.token_manager.get_token(target_acnt)
                    if not token:
                        raise TokenExpiredError(f"Failed to obtain token for account {target_acnt}.")
                    headers["authorization"] = f"Bearer {token}"
                
                async with self.session.request(method, url, headers=headers, json=payload) as response:
                    # [Retry-After Header Handling] 
                    # 서버에서 명시적인 냉각 시간을 요구할 경우 스로틀러에 즉각 반영
                    retry_after = response.headers.get("Retry-After")
                    if response.status == 429 and retry_after:
                        try:
                            wait_seconds = float(retry_after)
                            logger.warning(f"Retry-After detected: {wait_seconds}s. Backpressuring throttler...")
                            # 분당 버킷 수량 일시 소진 및 리필 지연 유도
                            throttler.minute_bucket.tokens = 0
                            throttler.minute_bucket.last_refill = time.monotonic() + wait_seconds
                            await asyncio.sleep(wait_seconds)
                        except ValueError:
                            pass

                    try:
                        data = await response.json()
                    except Exception as e:
                        text = await response.text()
                        raise KiwoomAPIError(f"Failed to parse JSON response: {text}") from e
                    
                    # Success
                    if response.status == 200:
                        # Kiwoom logical error handling
                        if data.get("return_code") != 0 and data.get("return_code") is not None:
                            # 429 에러가 return_code로 오는 경우도 대비
                            if data.get("return_code") in [429, "429"]:
                                delay = await self.rate_limit_backoff_waiter.wait(attempt)
                                logger.warning(f"Rate limit hit (Logic). Retrying in {delay}s... ({attempt+1}/{max_retries})")
                                continue
                            raise KiwoomAPIError(f"API Error [{data.get('return_code')}]: {data.get('return_msg')}", data.get("return_code"))
                        return data

                    # Key Error Status Handling
                    if response.status == 401:
                        if require_auth and auth_retry_allowed and not unauthorized_retried:
                            if not token_refreshed:
                                logger.warning("HTTP 401 received. Reissuing token and retrying request once.")
                                await self.issue_token()
                                token_refreshed = True
                            unauthorized_retried = True
                            continue
                        raise TokenExpiredError("Token is unauthorized or expired", data.get("return_code"))
                    
                    if response.status == 429:
                        delay = await self.rate_limit_backoff_waiter.wait(attempt)
                        logger.warning(f"Rate limit exceeded (HTTP 429). Retrying in {delay}s... ({attempt+1}/{max_retries})")
                        continue
                    
                    # 기타 에러 발생 시 즉시 예외 발생
                    raise KiwoomAPIError(f"HTTP Error {response.status}: {data.get('return_msg')}", data.get("return_code"))
            
            raise RateLimitExceededError(f"Max retries ({max_retries}) reached for Rate Limit.")

    async def issue_token(self) -> Dict[str, Any]:
        """au10001: 접근토큰 발급"""
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key
        }
        
        data = await self._request("POST", "/oauth2/token", api_id="au10001", 
                                   payload=payload, require_auth=False)
        
        token = data.get("token")
        expires_dt = data.get("expires_dt")
        
        if token:
            target_acnt = ACCOUNTS[0] if ACCOUNTS else "DEFAULT"
            self.token_manager.save_token(target_acnt, token, expires_dt)
            logger.info(f"Kiwoom OAuth Token issued successfully for {target_acnt}. Expires: {expires_dt}")
            
        return data

    async def revoke_token(self) -> Dict[str, Any]:
        """au10002: 접근토큰 폐기"""
        token = self.token_manager.get_token()
        if not token:
            logger.warning("No token found to revoke. Skipping.")
            return {}
            
        payload = {
            "appkey": self.app_key,
            "secretkey": self.secret_key,
            "token": token
        }
        
        data = await self._request("POST", "/oauth2/revoke", api_id="au10002", 
                                   payload=payload, require_auth=True)
        
        self.token_manager.clear()
        logger.info("Kiwoom OAuth Token revoked successfully.")
        return data

    async def get_order_executions(
        self, 
        acnt_no: str,
        stk_cd: str, 
        qry_tp: str = "0", 
        sell_tp: str = "0", 
        ord_no: str = "", 
        stex_tp: str = "0",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka10076: 체결요청
        계좌의 당일 혹은 과거 주문 체결 내역을 조회합니다.
        
        Args:
            stk_cd: 종목코드 (""일 경우 qry_tp="0" 전체조회)
            qry_tp: 조회구분 (0:전체, 1:종목)
            sell_tp: 매도수구분 (0:전체, 1:매도, 2:매수)
            ord_no: 주문번호 (입력한 주문번호 보다 과거 체결내역 조회, 최신은 "")
            stex_tp: 거래소구분 (0:통합, 1:KRX, 2:NXT)
            cont_yn: 연속조회여부 ("Y" or "N")
            next_key: 연속조회키
        """
        payload = {
            "acnt_no": acnt_no,
            "stk_cd": stk_cd,
            "qry_tp": qry_tp,
            "sell_tp": sell_tp,
            "ord_no": ord_no,
            "stex_tp": stex_tp
        }
        
        return await self._request("POST", "/api/dostk/acnt", api_id="ka10076", 
                                   payload=payload, require_auth=True, 
                                   cont_yn=cont_yn, next_key=next_key)

    async def get_open_orders(
        self,
        acnt_no: str,
        stk_cd: str = "",
        all_stk_tp: str = "1",
        trde_tp: str = "0",
        stex_tp: str = "0",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka10075: 미체결요청
        계좌의 현재 미체결된 주문 내역을 조회합니다.

        Args:
            acnt_no: 계좌번호
            stk_cd: 종목코드 (all_stk_tp="1"일 때 필수)
            all_stk_tp: 전체종목구분 (0:전체, 1:종목)
            trde_tp: 매매구분 (0:전체, 1:매도, 2:매수)
            stex_tp: 거래소구분 (0:통합, 1:KRX, 2:NXT)
        """
        payload = {
            "acnt_no": acnt_no,
            "all_stk_tp": all_stk_tp,
            "trde_tp": trde_tp,
            "stex_tp": stex_tp
        }
        if all_stk_tp == "1":
            payload["stk_cd"] = stk_cd
        
        return await self._request("POST", "/api/dostk/acnt", api_id="ka10075",
                                   payload=payload, require_auth=True,
                                   cont_yn=cont_yn, next_key=next_key)

    async def cancel_order(
        self,
        acnt_no: str,
        stk_cd: str,
        orig_ord_no: str,
        cncl_qty: Union[str, int] = "0",
        dmst_stex_tp: str = "KRX"
    ) -> Dict[str, Any]:
        """
        kt10003: 주식 취소주문
        미체결 주문을 취소합니다.

        Args:
            acnt_no: 계좌번호
            stk_cd: 종목코드
            orig_ord_no: 원주문번호
            cncl_qty: 취소수량 ("0": 전량 취소)
            dmst_stex_tp: 국내거래소구분 (KRX, NXT, SOR)
        """
        payload = {
            "dmst_stex_tp": dmst_stex_tp,
            "acnt_no": acnt_no,
            "orig_ord_no": orig_ord_no,
            "stk_cd": stk_cd,
            "cncl_qty": str(cncl_qty)
        }
        return await self._request("POST", "/api/dostk/ordr", api_id="kt10003",
                                   payload=payload, require_auth=True)

    async def get_minute_data(
        self, 
        stk_cd: str, 
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka10006: 주식시분요청
        당일 특정 시점의 고점/저점 추적 초기화를 위해 데이터를 조회합니다.
        
        Args:
            stk_cd: 종목코드 (KRX:039490, NXT:039490_NX, SOR:039490_AL)
        """
        payload = {
            "stk_cd": stk_cd
        }
        
        return await self._request("POST", "/api/dostk/mrkcond", api_id="ka10006", 
                                   payload=payload, require_auth=True, 
                                   cont_yn=cont_yn, next_key=next_key)

    async def get_minute_chart_data(
        self,
        stk_cd: str,
        tic_scope: str = "1",
        upd_stkpc_tp: str = "1",
        base_dt: str = "",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka10080: 주식분봉차트조회요청
        과거 특정 시점부터의 고점을 추적하기 위해 분봉 차트 데이터를 조회합니다.
        
        Args:
            stk_cd: 종목코드
            tic_scope: 틱범위 (1:1분, 3:3분, 5:5분, 10:10분, 15:15분, 30:30분, 45:45분, 60:60분)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
            base_dt: 기준일자 (YYYYMMDD) - 없으면 오늘부터 역순
        """
        payload = {
            "stk_cd": stk_cd,
            "tic_scope": tic_scope,
            "upd_stkpc_tp": upd_stkpc_tp,
        }
        if base_dt:
            payload["base_dt"] = base_dt
            
        return await self._request("POST", "/api/dostk/chart", api_id="ka10080",
                                   payload=payload, require_auth=True,
                                   cont_yn=cont_yn, next_key=next_key)

    async def get_daily_chart_data(
        self,
        stk_cd: str,
        base_dt: str,
        upd_stkpc_tp: str = "1",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka10081: 주식일봉차트조회요청
        분봉 데이터가 부족할 경우 더 과거의 고점을 추적하기 위해 일봉 차트 데이터를 조회합니다.

        Args:
            stk_cd: 종목코드
            base_dt: 기준일자 (YYYYMMDD)
            upd_stkpc_tp: 수정주가구분 (0 or 1)
        """
        payload = {
            "stk_cd": stk_cd,
            "base_dt": base_dt,
            "upd_stkpc_tp": upd_stkpc_tp,
        }
        return await self._request("POST", "/api/dostk/chart", api_id="ka10081",
                                   payload=payload, require_auth=True,
                                   cont_yn=cont_yn, next_key=next_key)

    async def get_stock_info(self, stk_cd: str) -> Dict[str, Any]:
        """
        ka10001: 주식기본정보요청
        종목코드로 종목명, 시가총액 등 기본 정보를 조회합니다.

        Args:
            stk_cd: 종목코드 (KRX:039490, NXT:039490_NX, SOR:039490_AL)
        """
        payload = {
            "stk_cd": stk_cd
        }
        
        return await self._request("POST", "/api/dostk/stkinfo", api_id="ka10001",
                                   payload=payload, require_auth=True)

    async def get_stock_quote(self, stk_cd: str) -> Dict[str, Any]:
        """
        ka10004: 주식호가요청
        특정 종목의 매도/매수 10단계 호가 및 잔량 정보를 조회합니다.

        Args:
            stk_cd: 종목코드
        """
        payload = {
            "stk_cd": stk_cd
        }
        
        return await self._request("POST", "/api/dostk/mrkcond", api_id="ka10004",
                                   payload=payload, require_auth=True)


    async def _place_order(
        self,
        api_id: str,
        acnt_no: str,
        stk_cd: str,
        ord_qty: int,
        ord_uv: str = "",
        trde_tp: str = "3",
        cond_uv: str = "",
        dmst_stex_tp: str = "KRX"
    ) -> Dict[str, Any]:
        """주문 공통 래퍼(Wrapper) (kt10000, kt10001 공용)"""
        payload = {
            "dmst_stex_tp": dmst_stex_tp,
            "acnt_no": acnt_no,
            "stk_cd": stk_cd,
            "ord_qty": str(ord_qty),
            "ord_uv": ord_uv,
            "trde_tp": trde_tp,
            "cond_uv": cond_uv
        }
        
        return await self._request("POST", "/api/dostk/ordr", api_id=api_id, 
                                   payload=payload, require_auth=True)

    async def place_buy_order(
        self, 
        acnt_no: str,
        stk_cd: str, 
        ord_qty: int, 
        ord_uv: str = "", 
        trde_tp: str = "3"
    ) -> Dict[str, Any]:
        """
        kt10000: 주식 매수주문
        - 기본 trde_tp(매매구분)는 '3'(시장가) 입니다.
        """
        return await self._place_order("kt10000", acnt_no, stk_cd, ord_qty, ord_uv, trde_tp)

    async def get_account_balance(
        self, 
        qry_tp: str = "1", 
        dmst_stex_tp: str = "KRX",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        kt00018: 계좌평가잔고내역요청
        당일 계좌별 잔고를 조회하여 수동 편입된 종목을 확인합니다.
        
        Args:
            qry_tp: 조회구분 (1:합산, 2:개별)
            dmst_stex_tp: 국내거래소구분 (KRX:한국거래소, NXT:넥스트트레이드)
        """
        payload = {
            "qry_tp": qry_tp,
            "dmst_stex_tp": dmst_stex_tp
        }
        
        return await self._request("POST", "/api/dostk/acnt", api_id="kt00018", 
                                   payload=payload, require_auth=True, 
                                   cont_yn=cont_yn, next_key=next_key)

    async def place_sell_order(
        self, 
        acnt_no: str,
        stk_cd: str, 
        ord_qty: int, 
        ord_uv: str = "", 
        trde_tp: str = "3"
    ) -> Dict[str, Any]:
        """
        kt10001: 주식 매도주문
        - 기본 trde_tp(매매구분)는 '3'(시장가) 입니다.
        """
        return await self._place_order("kt10001", acnt_no, stk_cd, ord_qty, ord_uv, trde_tp)

    async def modify_order(
        self,
        acnt_no: str,
        orig_ord_no: str,
        stk_cd: str,
        mdfy_qty: int,
        mdfy_uv: str,
        mdfy_cond_uv: str = "",
        dmst_stex_tp: str = "KRX"
    ) -> Dict[str, Any]:
        """
        kt10002: 주식 정정주문
        기존 미체결 주문의 수량 또는 단가를 정정합니다.

        Args:
            acnt_no: 계좌번호
            orig_ord_no: 정정 대상 원주문번호
            stk_cd: 종목코드
            mdfy_qty: 정정할 수량
            mdfy_uv: 정정할 단가
            mdfy_cond_uv: 정정조건단가 (선택)
            dmst_stex_tp: 거래소구분 (KRX/NXT/SOR)
        """
        payload = {
            "dmst_stex_tp": dmst_stex_tp,
            "acnt_no": acnt_no,
            "orig_ord_no": orig_ord_no,
            "stk_cd": stk_cd,
            "mdfy_qty": str(mdfy_qty),
            "mdfy_uv": mdfy_uv,
            "mdfy_cond_uv": mdfy_cond_uv
        }
        return await self._request("POST", "/api/dostk/ordr", api_id="kt10002",
                                   payload=payload, require_auth=True)

    async def get_theme_groups(
        self,
        qry_tp: str = "0",
        stk_cd: str = "",
        date_tp: str = "1",
        thema_nm: str = "",
        flu_pl_amt_tp: str = "3",
        stex_tp: str = "3",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka90001: 테마그룹별요청
        테마별 등락율 정보를 조회합니다.

        Args:
            qry_tp: 검색구분 (0:전체검색, 1:테마검색, 2:종목검색)
            stk_cd: 검색하려는 종목코드
            date_tp: 날짜구분 (1일 ~ 99일 입력)
            thema_nm: 검색하려는 테마명
            flu_pl_amt_tp: 등락수익구분 (1:상위기간수익률, 2:하위기간수익률, 3:상위등락률, 4:하위등락률)
            stex_tp: 거래소구분 (1:KRX, 2:NXT, 3:통합)
        """
        payload = {
            "qry_tp": qry_tp,
            "stk_cd": stk_cd,
            "date_tp": date_tp,
            "thema_nm": thema_nm,
            "flu_pl_amt_tp": flu_pl_amt_tp,
            "stex_tp": stex_tp
        }
        return await self._request("POST", "/api/dostk/thme", api_id="ka90001",
                                   payload=payload, require_auth=True,
                                   cont_yn=cont_yn, next_key=next_key)

    async def get_theme_details(
        self,
        theme_grp_cd: str,
        date_tp: str = "1",
        stex_tp: str = "3",
        cont_yn: str = "N",
        next_key: str = ""
    ) -> Dict[str, Any]:
        """
        ka90002: 테마구성종목요청
        특정 테마의 구성 종목 정보를 조회합니다.

        Args:
            theme_grp_cd: 테마그룹코드
            date_tp: 날짜구분 (1일 ~ 99일 입력)
            stex_tp: 거래소구분 (1:KRX, 2:NXT, 3:통합)
        """
        payload = {
            "thema_grp_cd": theme_grp_cd,
            "date_tp": date_tp,
            "stex_tp": stex_tp
        }
        return await self._request("POST", "/api/dostk/thme", api_id="ka90002",
                                   payload=payload, require_auth=True,
                                   cont_yn=cont_yn, next_key=next_key)

