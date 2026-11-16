"""
可插拔问答缓存：
- 默认内存 LRU + TTL（本机无 Redis 也能用）
- 配置 REDIS_URL 后自动切换 Redis（部署到服务器一键启用）
缓存 key = 归一化问题 + 索引版本指纹（文档增删改自动失效）+ 进程随机种子
（跨重启自动失效，杜绝 Redis 场景的陈旧缓存）。
"""
import hashlib
import re
import threading
import time
import uuid
from collections import OrderedDict

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

# 进程随机种子：混入 key，重启后所有缓存 key 失效（安全兜底）
_PROCESS_SEED = uuid.uuid4().hex

# 索引版本计数器：文档入库完成/删除时 +1（进程内）
_index_version = 0
_version_lock = threading.Lock()


def bump_index_version() -> int:
    """索引变化时调用（入库完成/文档删除），缓存 key 随之失效"""
    global _index_version
    with _version_lock:
        _index_version += 1
        return _index_version


class MemoryTTLCache:
    """线程安全的内存 LRU + TTL 缓存"""

    def __init__(self, max_size: int = 256, ttl: int = 600):
        self._max_size = max_size
        self._ttl = ttl
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expire_at, value = item
            if time.time() > expire_at:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value, ttl: int | None = None) -> None:
        with self._lock:
            self._data[key] = (time.time() + (ttl or self._ttl), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)  # LRU 淘汰


class RedisCache:
    """Redis 缓存（部署环境用，懒连接 + 失败降级内存）"""

    def __init__(self, url: str):
        import redis

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._ttl = get_settings().cache_ttl

    def get(self, key: str):
        try:
            import json

            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:  # noqa: BLE001 —— Redis 异常降级不阻塞问答
            log.warning("cache.redis_get_failed", error=str(exc))
            return None

    def set(self, key: str, value, ttl: int | None = None) -> None:
        try:
            import json

            self._client.setex(key, ttl or self._ttl, json.dumps(value, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            log.warning("cache.redis_set_failed", error=str(exc))


_cache = None


def get_cache():
    """全局缓存单例：有 REDIS_URL 用 Redis，否则内存 LRU"""
    global _cache
    if _cache is None:
        settings = get_settings()
        if settings.redis_url:
            try:
                _cache = RedisCache(settings.redis_url)
                log.info("cache.backend", backend="redis")
            except Exception as exc:  # noqa: BLE001 —— Redis 不可用降级内存
                log.warning("cache.redis_unavailable", error=str(exc))
                _cache = MemoryTTLCache(settings.cache_size, settings.cache_ttl)
        else:
            _cache = MemoryTTLCache(settings.cache_size, settings.cache_ttl)
            log.info("cache.backend", backend="memory")
    return _cache


def qa_cache_key(query: str, history: list[dict] | None = None) -> str:
    """问答缓存 key：归一化问题 + 最近历史指纹 + 索引版本 + 进程种子

    历史指纹解决多轮指代问题：同一句「它多少钱」在不同上文下答案不同，
    不能命中同一个缓存条目。
    """
    normalized = re.sub(r"\s+", "", query).lower()
    hist_raw = ""
    for item in (history or [])[-4:]:
        role = item.get("role") or ""
        content = re.sub(r"\s+", "", item.get("content") or "")[:200]
        hist_raw += f"|{role}:{content}"
    hist_fp = (
        hashlib.sha256(hist_raw.encode("utf-8")).hexdigest()[:12] if hist_raw else "none"
    )
    raw = f"{normalized}|h{hist_fp}|v{_index_version}|{_PROCESS_SEED}"
    return "qa:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()
