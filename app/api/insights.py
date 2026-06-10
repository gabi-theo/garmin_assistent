import uuid
import logging
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.db_models import Insight as DBInsight
from app.models.schemas import InsightResponse
from app.api.deps import get_current_user, AuthenticatedUser, rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/insights", tags=["Insights"], dependencies=[rate_limit])


@router.get("/latest", response_model=List[InsightResponse])
async def get_latest_insights(
    limit: int = Query(5, ge=1, le=50, description="Max number of insights to return"),
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Fetches the latest N generated coaching insights from long-term storage."""
    user_uuid = uuid.UUID(current_user.id)
    logger.info(f"Fetching latest {limit} insights for user {user_uuid}")

    stmt = (
        select(DBInsight)
        .where(DBInsight.user_id == user_uuid)
        .order_by(DBInsight.created_at.desc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    insights = result.scalars().all()
    
    return insights
