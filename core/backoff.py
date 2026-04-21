import asyncio
import random
import logging
from abc import ABC, abstractmethod
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

class BackoffWaiter(ABC):
    """
    재시도 대기 전략의 추상 기본 클래스입니다.
    """
    @abstractmethod
    async def wait(self, attempt: int):
        """특정 시도 횟수에 따라 대기합니다."""
        pass

    @abstractmethod
    def reset(self):
        """대기 상태를 초기화합니다."""
        pass

class ExponentialBackoffWaiter(BackoffWaiter):
    """
    지수 백오프(Exponential Backoff) 전략을 구현한 클래스입니다.
    시도 횟수가 늘어날수록 대기 시간이 기하급수적으로 증가하며, 지터(Jitter)를 추가할 수 있습니다.
    """
    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        factor: float = 2.0,
        jitter_ratio: float = 0.1,
        sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_fn: Callable[[float, float], float] = random.uniform
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.factor = factor
        self.jitter_ratio = jitter_ratio
        self.sleep_fn = sleep_fn
        self.random_fn = random_fn

    async def wait(self, attempt: int):
        """
        지수 백오프 공식에 따라 대기 시간을 계산하고 잠듭니다.
        delay = min(max_delay, base_delay * (factor ^ attempt))
        """
        if attempt <= 0:
            return

        # 기본 지수 시간 계산
        delay = min(self.max_delay, self.base_delay * (self.factor ** (attempt - 1)))
        
        # 지터(Jitter) 추가: 네트워크 폭주(Thundering Herd) 방지
        if self.jitter_ratio > 0:
            jitter = delay * self.jitter_ratio
            delay = self.random_fn(delay - jitter, delay + jitter)

        logger.debug(f"Backoff waiting for {delay:.2f}s (attempt {attempt})")
        await self.sleep_fn(delay)

    def reset(self):
        """지수 백오프는 상태를 별도로 가지지 않으므로 초기화가 필요 없지만 인터페이스 준수를 위해 구현합니다."""
        pass
