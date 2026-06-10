import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, literal_column

from app.db.session import get_db
from app.models.db_models import Metric as DBMetric
from app.models.schemas import MetricResponse
from app.redis.client import get_redis_client
from app.api.deps import get_current_user, AuthenticatedUser, rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["Metrics"], dependencies=[rate_limit])


@router.get("/{metric}", response_model=List[Dict[str, Any]])
async def get_metrics(
    metric: str,
    days: int = Query(7, ge=1, le=90, description="Number of days of history to fetch"),
    bucket: Optional[str] = Query(None, description="Time bucket interval (e.g., '1 hour', '1 day') for TimescaleDB aggregation"),
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Fetches telemetry metrics. Returns <=24h from Redis hot cache, and >24h from TimescaleDB."""
    user_uuid = uuid.UUID(current_user.id)
    now = datetime.now(timezone.utc)
    boundary = now - timedelta(hours=24)
    start_time = now - timedelta(days=days)

    # 1. Handle bucketed aggregate query (Runs directly on TimescaleDB for speed & consistency)
    if bucket:
        # Determine casting based on metric schema
        # Sleep stores {"duration_seconds": ..., "score": ...}
        # Activity stores {"duration_minutes": ..., "calories": ...}
        # Others store a raw number
        # For daily health metrics, the last reading in each bucket is more meaningful
        # than the average (avoids zeros from failed polls dragging down real values).
        # TimescaleDB last(value, time) returns the JSONB value at the latest timestamp
        # in the bucket, which we then cast to float.
        if metric == "sleep":
            value_expr = "CAST(last(value, time)->>'score' AS DOUBLE PRECISION)"
        elif metric == "activity":
            value_expr = "CAST(last(value, time)->>'duration_minutes' AS DOUBLE PRECISION)"
        else:
            value_expr = "CAST(last(value, time)::text AS DOUBLE PRECISION)"

        logger.info(f"Executing TimescaleDB bucketed query for metric '{metric}' bucket '{bucket}'")
        try:
            query = (
                select(
                    func.time_bucket(text(f"interval '{bucket}'"), DBMetric.time).label("bucket_time"),
                    literal_column(value_expr).label("last_value")
                )
                .where(
                    DBMetric.user_id == user_uuid,
                    DBMetric.metric == metric,
                    DBMetric.time >= start_time
                )
                .group_by(text("bucket_time"))
                .order_by(text("bucket_time ASC"))
            )

            result = await db.execute(query)
            rows = result.all()
            return [
                {
                    "time": row[0].isoformat() if row[0] else None,
                    "value": row[1]
                }
                for row in rows if row[0] is not None
            ]
        except Exception as e:
            logger.error(f"Failed to execute time_bucket query: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Aggregation error. Ensure interval is valid (e.g. '1 hour', '1 day'). Details: {str(e)}"
            )

    # 2. Handle raw data retrieval (Cache + TimescaleDB union)
    logger.info(f"Fetching raw metrics for user {user_uuid} and metric '{metric}'")
    
    # A. Fetch recent data (<=24h) from Redis Sorted Set
    redis = await get_redis_client()
    redis_key = f"metrics:{current_user.id}:{metric}"
    
    min_score = boundary.timestamp()
    max_score = now.timestamp()
    
    raw_redis_data = await redis.zrangebyscore(redis_key, min_score, max_score)
    redis_metrics = []
    for item in raw_redis_data:
        try:
            data = json.loads(item)
            redis_metrics.append({
                "time": data["recorded_at"],
                "user_id": data["user_id"],
                "metric": data["metric"],
                "value": data["value"]
            })
        except Exception as e:
            logger.error(f"Error parsing cached metric element: {e}")

    # B. Fetch historical data (>24h) from TimescaleDB
    db_metrics = []
    if start_time < boundary:
        stmt = (
            select(DBMetric)
            .where(
                DBMetric.user_id == user_uuid,
                DBMetric.metric == metric,
                DBMetric.time >= start_time,
                DBMetric.time < boundary
            )
            .order_by(DBMetric.time.asc())
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        db_metrics = [
            {
                "time": r.time.isoformat(),
                "user_id": str(r.user_id),
                "metric": r.metric,
                "value": r.value
            }
            for r in rows
        ]

    # Combine results
    combined = db_metrics + redis_metrics
    
    # De-duplicate matching exact timestamps to avoid overlap discrepancies
    seen_timestamps = set()
    result_list = []
    for item in combined:
        ts = item["time"]
        if ts not in seen_timestamps:
            seen_timestamps.add(ts)
            result_list.append(item)

    return result_list
