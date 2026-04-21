import asyncio
import time
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class TokenBucket:
    """
    토큰 버킷 알고리즘을 구현한 클래스입니다.
    초당/분당 요청 제한을 관리합니다.
    """
    def __init__(self, capacity: int, fill_rate: float):
        self.capacity = capacity  # 최대 토큰 수
        self.fill_rate = fill_rate  # 초당 리필되는 토큰 수
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def consume(self, amount: float = 1.0):
        """
        토큰을 소비합니다. 토큰이 부족하면 충전될 때까지 대기(sleep)합니다.
        """
        async with self._get_lock():
            while True:
                self._refill()
                if self.tokens >= amount:
                    self.tokens -= amount
                    return
                
                # 부족한 토큰이 충전될 때까지 대기해야 할 시간 계산
                wait_time = (amount - self.tokens) / self.fill_rate
                await asyncio.sleep(wait_time)

    def _refill(self):
        """
        마지막 리필 이후 경과한 시간에 따라 토킷을 충전합니다.
        """
        now = time.monotonic()
        elapsed = now - self.last_refill
        
        if elapsed > 0:
            refill_amount = elapsed * self.fill_rate
            self.tokens = min(self.capacity, self.tokens + refill_amount)
            self.last_refill = now

class GlobalThrottler:
    """
    키움 Open API W의 글로벌 및 계좌별 호출 제한을 통합 관리하는 클래스입니다.
    기본 정책: 초당 4회, 분당 50회 제한.
    """
    def __init__(self, per_second: int = 4, per_minute: int = 50):
        # 전역 제한용 버킷
        self.per_second = per_second
        self.per_minute = per_minute
        self.second_bucket = TokenBucket(per_second, per_second)
        self.minute_bucket = TokenBucket(per_minute, per_minute / 60.0)
        
        # 계좌별 개별 제한
        self.account_locks: Dict[str, asyncio.Lock] = {}
        self._loop = None

    def _check_loop(self):
        """Detect loop changes and reset locks if necessary."""
        current_loop = asyncio.get_running_loop()
        if self._loop != current_loop:
            self.account_locks.clear()
            self.second_bucket._lock = None
            self.minute_bucket._lock = None
            self._loop = current_loop

    async def consume(self, account_no: Optional[str] = None):
        """
        API 호출 전 호출 제한을 체크하고 대기합니다.
        """
        self._check_loop()
        
        # 1. 분당 제한 체크 (가장 긴 주기)
        await self.minute_bucket.consume(1.0)
        
        # 2. 초당 제한 체크
        await self.second_bucket.consume(1.0)

        # 3. 계좌별 순차 처리 보장 (선택적)
        if account_no:
            if account_no not in self.account_locks:
                self.account_locks[account_no] = asyncio.Lock()
            # 계좌별로 아주 짧은 간격을 두어 서버 부하 분산
            async with self.account_locks[account_no]:
                await asyncio.sleep(0.05)

# 전역 싱글톤 인스턴스 생성
throttler = GlobalThrottler()
