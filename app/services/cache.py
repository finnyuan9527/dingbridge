import redis.asyncio as redis
from typing import Optional

from app.config import settings

class RedisManager:
    _client: Optional[redis.Redis] = None

    @classmethod
    def get_client(cls) -> redis.Redis:
        if cls._client is None:
            cls._client = redis.Redis(
                host=settings.redis.host,
                port=settings.redis.port,
                password=settings.redis.password,
                db=settings.redis.db,
                decode_responses=True,  # 自动解码为 str
            )
        return cls._client

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None

# 便捷访问入口
def get_redis() -> redis.Redis:
    return RedisManager.get_client()
