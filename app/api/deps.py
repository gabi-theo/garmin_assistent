import json
import logging
from fastapi import Header, HTTPException, status, Depends
from app.redis.client import get_redis_client
from app.redis.ratelimit import rate_limit_dependency

logger = logging.getLogger(__name__)


class AuthenticatedUser:
    """Lightweight user model representing the session user, loaded directly from Redis."""
    def __init__(self, user_id: str, email: str):
        self.id = user_id
        self.email = email


async def get_current_user(authorization: str = Header(..., description="Bearer token")) -> AuthenticatedUser:
    """Validates the session token from Redis. Bypasses TimescaleDB database hit entirely."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must follow 'Bearer <token>' schema"
        )
    
    token = authorization.split(" ")[1]
    redis = await get_redis_client()
    session_key = f"session:{token}"
    
    session_data = await redis.get(session_key)
    if not session_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or is invalid"
        )
        
    try:
        user_info = json.loads(session_data)
        return AuthenticatedUser(
            user_id=user_info["id"],
            email=user_info["email"]
        )
    except Exception as e:
        logger.error(f"Error parsing session JSON for token: {e}")
        # Fallback if only the raw UUID string was saved in the session
        return AuthenticatedUser(
            user_id=session_data,
            email=""
        )


# Export rate limiter dependency for routes
rate_limit = Depends(rate_limit_dependency)
