# app/shared/cache.py
import json
import structlog
from redis.asyncio import Redis, from_url
from app.core.config import settings

logger = structlog.get_logger(__name__)

CACHE_PREFIX = "exam_prep_cache:"

class RedisCache:
    def __init__(self):
        self._redis: Redis = from_url(settings.REDIS_URL, decode_responses=True)

    def _prefix_key(self, key: str) -> str:
        return f"{CACHE_PREFIX}{key}"

    async def get(self, key: str):
        try:
            val = await self._redis.get(self._prefix_key(key))
            if val:
                return json.loads(val)
        except Exception as exc:
            logger.warning("cache_get_failed", key=key, error=str(exc))
        return None

    async def set(self, key: str, value, ttl: int = settings.CACHE_TTL_DEFAULT):
        try:
            # ex=ttl garantiza que nunca se acumulen llaves que desborden los 30 MB
            await self._redis.set(self._prefix_key(key), json.dumps(value), ex=ttl)
        except Exception as exc:
            logger.warning("cache_set_failed", key=key, error=str(exc))

redis_cache = RedisCache()
