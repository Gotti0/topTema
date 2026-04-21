import asyncio
import logging
import time
from typing import Dict, Optional, Tuple
import aiohttp
from config.settings import API_DOMAIN, ACCOUNTS, get_api_keys

logger = logging.getLogger(__name__)

class TokenManager:
    """
    키움 Open API W의 OAuth2 접근 토큰(Access Token)을 관리하는 클래스입니다.
    토큰 발급, 저장 및 만료 전 자동 갱신 기능을 담당합니다.
    """
    def __init__(self):
        # 계좌별 토큰 저장소: {account_no: (token, expires_at)}
        self._tokens: Dict[str, Tuple[str, float]] = {}
        self._refresh_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def get_token(self, account_no: str) -> str:
        """
        계좌번호에 해당하는 유효한 토큰을 반환합니다.
        없거나 만료된 경우 새로 발급받습니다.
        """
        async with self._lock:
            token, expires_at = self._tokens.get(account_no, (None, 0))
            
            # 만료 5분 전이면 새로 발급
            if not token or time.time() > (expires_at - 300):
                token, expires_in = await self._issue_token(account_no)
                self._tokens[account_no] = (token, time.time() + expires_in)
                
                # 자동 갱신 태스크 스케줄링 (만료 30분 전 갱신)
                self._schedule_refresh(account_no, expires_in)
                
            result_token = self._tokens[account_no][0]
            logger.debug(f"get_token for {account_no} returning: {result_token[:10]}...")
            return result_token

    async def _issue_token(self, account_no: str) -> Tuple[str, int]:
        """
        키움 서버에 토큰 발급을 요청합니다 (au10001).
        """
        app_key, secret_key = get_api_keys(account_no)
        if not app_key or not secret_key:
            raise ValueError(f"API Keys not found for account: {account_no}")

        url = f"{API_DOMAIN}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": secret_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Failed to issue token for {account_no}: {error_text}")
                    raise Exception(f"Token issuance failed: {response.status}")
                
                data = await response.json()
                # 키움 API W 실사양: 'token' 및 'expires_dt' (YYYYMMDDHHMMSS)
                token = data.get("token")
                expires_dt_str = data.get("expires_dt")
                
                if not token:
                    logger.error(f"Response from Kiwoom does not contain 'token': {data}")
                    raise Exception("Token missing in response")

                # expires_dt(YYYYMMDDHHMMSS)를 timestamp로 변환하여 남은 시간 계산
                try:
                    from datetime import datetime
                    expires_at = datetime.strptime(expires_dt_str, "%Y%m%d%H%M%S").timestamp()
                    expires_in = int(expires_at - time.time())
                except Exception as e:
                    logger.warning(f"Failed to parse expires_dt ({expires_dt_str}), defaulting to 3600s: {e}")
                    expires_in = 3600
                
                logger.info(f"Successfully issued token for account {account_no}. Expires at {expires_dt_str} ({expires_in}s remaining)")
                return token, expires_in

    def _schedule_refresh(self, account_no: str, expires_in: int):
        """
        토큰 만료 전 자동으로 갱신하도록 비동기 태스크를 예약합니다.
        """
        # 기존 태스크가 있다면 취소
        if account_no in self._refresh_tasks:
            self._refresh_tasks[account_no].cancel()

        # 만료 30분 전 또는 전체 기간의 75% 시점 중 빠른 때 갱신
        refresh_after = max(60, expires_in - 1800) 
        
        async def refresh_job():
            try:
                await asyncio.sleep(refresh_after)
                logger.info(f"Refreshing token for account {account_no}...")
                await self.get_token(account_no)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error in token refresh job for {account_no}: {e}")
                # 실패 시 잠시 후 재시도
                await asyncio.sleep(60)
                self._schedule_refresh(account_no, 600)

        self._refresh_tasks[account_no] = asyncio.create_task(refresh_job())

    def save_token(self, account_no: str, token: str, expires_dt_str: str):
        """
        외부에서 발급받은 토큰을 강제로 저장하고 갱신 태스크를 예약합니다.
        """
        try:
            from datetime import datetime
            expires_at = datetime.strptime(expires_dt_str, "%Y%m%d%H%M%S").timestamp()
            expires_in = int(expires_at - time.time())
        except Exception:
            expires_in = 3600
        
        self._tokens[account_no] = (token, time.time() + expires_in)
        self._schedule_refresh(account_no, expires_in)

    async def close(self):
        """
        모든 갱신 태스크를 중단하고 자원을 해제합니다.
        """
        for account_no, task in list(self._refresh_tasks.items()):
            if not task.done():
                task.cancel()
        
        if self._refresh_tasks:
            # 모든 태스크가 취소될 때까지 대기
            await asyncio.gather(*self._refresh_tasks.values(), return_exceptions=True)
            self._refresh_tasks.clear()
        
        logger.info("TokenManager: 모든 백그라운드 갱신 태스크가 종료되었습니다.")
