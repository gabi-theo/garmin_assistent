import logging
from typing import Optional
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Single global redis client instance
_redis_client: Optional[aioredis.Redis] = None


async def init_redis() -> aioredis.Redis:
    """Initializes the async Redis client connection pool."""
    global _redis_client
    if _redis_client is None:
        logger.info("Initializing async Redis client pool...")
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True  # Automatically decode bytes to str
        )
    return _redis_client


async def get_redis_client() -> aioredis.Redis:
    """Returns the global active Redis client instance."""
    global _redis_client
    if _redis_client is None:
        await init_redis()
    assert _redis_client is not None
    return _redis_client


async def close_redis() -> None:
    """Closes the Redis client connection pool."""
    global _redis_client
    if _redis_client is not None:
        logger.info("Closing async Redis client pool...")
        await _redis_client.close()
        _redis_client = None
