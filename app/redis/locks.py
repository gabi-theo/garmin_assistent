import logging
from typing import Optional
from app.redis.client import get_redis_client

logger = logging.getLogger(__name__)

# Lua script to release lock atomically only if the identifier matches
RELEASE_LUA_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


async def acquire_lock(lock_key: str, identifier: str, ttl_seconds: int = 30) -> bool:
    """Acquires a distributed lock atomically."""
    redis = await get_redis_client()
    try:
        # SET lock_key identifier EX ttl_seconds NX
        result = await redis.set(lock_key, identifier, ex=ttl_seconds, nx=True)
        return bool(result)
    except Exception as e:
        logger.error(f"Error acquiring lock {lock_key}: {e}")
        return False


async def release_lock(lock_key: str, identifier: Optional[str] = None) -> bool:
    """Releases a distributed lock. Evaluates Lua script if identifier is provided, else deletes directly."""
    redis = await get_redis_client()
    try:
        if identifier:
            result = await redis.eval(RELEASE_LUA_SCRIPT, 1, lock_key, identifier)
            return bool(result)
        else:
            result = await redis.delete(lock_key)
            return bool(result)
    except Exception as e:
        logger.error(f"Error releasing lock {lock_key}: {e}")
        return False
