# app/shared/cache.py
import json
from redis.asyncio import Redis, from_url
from app.core.config import settings

class RedisCache:
    def __init__(self):
        self._redis: Redis = from_url(settings.REDIS_URL)

    async def get(self, key: str):
        try:
            val = await self._redis.get(key)
            if val:
                return json.loads(val)
        except Exception:
            pass
        return None

    async def set(self, key: str, value, ttl: int = settings.CACHE_TTL_DEFAULT):
        try:
            await self._redis.set(key, json.dumps(value), ex=ttl)
        except Exception:
            pass

redis_cache = RedisCache()
