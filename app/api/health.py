import uuid
import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.db.session import get_db
from app.models.db_models import User as DBUser
from app.redis.client import get_redis_client
from app.garmin.poller import get_user_poller_status, manual_poll_user
from app.api.deps import get_current_user, AuthenticatedUser, rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"], dependencies=[rate_limit])


@router.get("/status")
async def get_status(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Returns connectivity and Garmin poller status for the current user."""

    # Database check
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        db_status = "error"

    # Redis check
    try:
        redis = await get_redis_client()
        await redis.ping()
        redis_status = "connected"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        redis_status = "error"

    # Garmin credentials check
    stmt = select(DBUser).where(DBUser.id == uuid.UUID(current_user.id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    garmin_configured = bool(
        user and user.garmin_username and user.garmin_password_encrypted
    )
    garmin_username = user.garmin_username if garmin_configured else None

    # Poller runtime status
    poller = await get_user_poller_status(current_user.id)

    return {
        "database": db_status,
        "redis": redis_status,
        "garmin": {
            "configured": garmin_configured,
            "account": garmin_username,
            **poller,
        },
    }


@router.post("/poll")
async def trigger_poll(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Immediately runs one Garmin fetch cycle for the current user."""
    stmt = select(DBUser).where(DBUser.id == uuid.UUID(current_user.id))
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.garmin_username or not user.garmin_password_encrypted:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Garmin credentials not configured.")

    return await manual_poll_user(
        user_id=str(user.id),
        email=user.garmin_username,
        password_encrypted=user.garmin_password_encrypted,
    )
