"""
令牌桶限流（M5，方案性能清单⑭）：
每用户问答默认 10 次/分钟（.env 可调），超限 429。
内存实现（本机无 Redis）；Redis 场景可扩展（当前规模内存足够）。
"""
import threading
import time

from app.core.config import get_settings
from app.core.exceptions import BizError

_buckets: dict[str, "TokenBucket"] = {}
_lock = threading.Lock()


class TokenBucket:
    """经典令牌桶：容量 capacity，按 rate_per_min 速率回填"""

    def __init__(self, capacity: int, rate_per_min: int):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_per_sec = rate_per_min / 60.0
        self.last_refill = time.monotonic()

    def try_take(self) -> bool:
        """尝试取一个令牌：成功 True，桶空 False"""
        now = time.monotonic()
        self.tokens = min(
            self.capacity,
            self.tokens + (now - self.last_refill) * self.refill_per_sec,
        )
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


def check_rate_limit(user_id: int, scope: str = "chat") -> None:
    """
    限流检查：超限抛 429 BizError。
    scope 预留多维度（chat/upload），当前 chat 一个桶。
    """
    settings = get_settings()
    key = f"{scope}:{user_id}"
    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            bucket = TokenBucket(settings.rate_limit_chat_per_min, settings.rate_limit_chat_per_min)
            _buckets[key] = bucket
    if not bucket.try_take():
        raise BizError(
            f"请求过于频繁，请 {60 // max(settings.rate_limit_chat_per_min, 1)} 秒后再试",
            code="RATE_LIMITED",
            status_code=429,
        )
