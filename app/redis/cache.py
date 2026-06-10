import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.redis.client import get_redis_client

logger = logging.getLogger(__name__)


async def cache_metric(
    user_id: str,
    metric: str,
    value: Any,
    recorded_at: str,
    source: str = "garmin"
) -> None:
    """Caches metric in Redis Sorted Set and queues it for TimescaleDB flush."""
    redis = await get_redis_client()
    payload = {
        "user_id": user_id,
        "metric": metric,
        "value": value,
        "recorded_at": recorded_at,
        "source": source
    }
    payload_str = json.dumps(payload)

    # Convert ISO8601 timestamp to Unix epoch score
    try:
        dt = datetime.fromisoformat(recorded_at.replace("+00:00Z", "+00:00").replace("Z", "+00:00"))
        timestamp = dt.timestamp()
    except Exception as e:
        logger.warning(f"Could not parse ISO timestamp '{recorded_at}', using current time: {e}")
        timestamp = datetime.now(timezone.utc).timestamp()

    sorted_set_key = f"metrics:{user_id}:{metric}"
    flush_queue_key = "metrics:flush_queue"

    # Write-through pipeline
    async with redis.pipeline(transaction=True) as pipe:
        # Cache for 24h fast access
        pipe.zadd(sorted_set_key, {payload_str: timestamp})
        pipe.expire(sorted_set_key, 86400)  # 24 hours TTL
        # Queue for TimescaleDB persistence
        pipe.rpush(flush_queue_key, payload_str)
        await pipe.execute()


async def flush_queue_to_db() -> None:
    """Pops all accumulated metrics from Redis and bulk-inserts them into TimescaleDB."""
    redis = await get_redis_client()
    flush_queue_key = "metrics:flush_queue"

    # Check queue length
    queue_len = await redis.llen(flush_queue_key)
    if queue_len == 0:
        return

    logger.info(f"Flushing {queue_len} telemetry records from Redis to TimescaleDB...")

    # Fetch and trim the popped slice atomically
    async with redis.pipeline(transaction=True) as pipe:
        pipe.lrange(flush_queue_key, 0, queue_len - 1)
        pipe.ltrim(flush_queue_key, queue_len, -1)
        results = await pipe.execute()

    raw_items = results[0]
    if not raw_items:
        return

    from app.models.db_models import Metric as DBMetric
    from app.db.session import async_session_factory

    parsed_metrics = []
    for item in raw_items:
        try:
            data = json.loads(item)
            dt = datetime.fromisoformat(data["recorded_at"].replace("+00:00Z", "+00:00").replace("Z", "+00:00"))
            parsed_metrics.append({
                "time": dt,
                "user_id": data["user_id"],
                "metric": data["metric"],
                "value": data["value"]
            })
        except Exception as e:
            logger.error(f"Failed to parse queued metric data for DB flush: {e}, payload: {item}")

    if not parsed_metrics:
        return

    async with async_session_factory() as session:
        try:
            # Batch insert using postgres ON CONFLICT DO NOTHING to guarantee idempotency
            for chunk in _chunk_list(parsed_metrics, 500):
                for metric_dict in chunk:
                    stmt = insert(DBMetric).values(
                        time=metric_dict["time"],
                        user_id=metric_dict["user_id"],
                        metric=metric_dict["metric"],
                        value=metric_dict["value"]
                    ).on_conflict_do_nothing()
                    await session.execute(stmt)
            await session.commit()
            logger.info(f"Successfully persisting {len(parsed_metrics)} records in TimescaleDB.")
        except Exception as e:
            logger.error(f"TimescaleDB bulk-insert failed: {e}. Re-queueing items in Redis.")
            await session.rollback()
            # Push back to redis queue to prevent telemetry loss
            async with redis.pipeline(transaction=True) as rollback_pipe:
                for item in raw_items:
                    rollback_pipe.lpush(flush_queue_key, item)
                await rollback_pipe.execute()


def _chunk_list(lst: list, n: int):
    """Helper to partition list into chunks of size n."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


async def start_cache_flusher() -> None:
    """Async loop running as a background task to flush the queue every 60s."""
    logger.info("Starting background TimescaleDB cache flush worker...")
    while True:
        try:
            await asyncio.sleep(60)
            await flush_queue_to_db()
        except asyncio.CancelledError:
            logger.info("Cache flush task received cancel signal. Performing final flush...")
            try:
                await flush_queue_to_db()
            except Exception as e:
                logger.error(f"Final flush failed during shutdown: {e}")
            break
        except Exception as e:
            logger.error(f"Unexpected error in cache flusher: {e}")
