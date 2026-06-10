import logging
from fastapi import Request, HTTPException, status
from app.redis.client import get_redis_client

logger = logging.getLogger(__name__)


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency to rate limit all endpoints to 60 requests/minute per user/IP."""
    redis = await get_redis_client()
    
    # 1. Determine identity (authenticated user ID or client IP)
    identity = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        # Check if session exists in Redis
        user_id = await redis.get(f"session:{token}")
        if user_id:
            identity = user_id

    if not identity:
        # Fallback to client host IP for unauthenticated routes (e.g. login/register)
        identity = request.client.host if request.client else "unknown_ip"

    # 2. Increment and check rate limit key
    endpoint = request.url.path
    key = f"ratelimit:{identity}:{endpoint}"

    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.ttl(key)
        results = await pipe.execute()

    count = results[0]
    ttl = results[1]

    # If key is newly created, set 60s expiration
    if count == 1 or ttl == -1:
        await redis.expire(key, 60)
        ttl = 60

    # Max 60 requests per minute
    if count > 60:
        retry_after = ttl if ttl > 0 else 60
        logger.warning(f"Rate limit exceeded for identity {identity} on endpoint {endpoint}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(retry_after)}
        )
