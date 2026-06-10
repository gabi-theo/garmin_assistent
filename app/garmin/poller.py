import json
import logging
from datetime import datetime, timezone

from app.config import settings
from app.garmin.client import AsyncGarminClient
from app.kafka.producer import publish_metric
from app.redis.client import get_redis_client

logger = logging.getLogger(__name__)


def _is_rate_limited(exc: Exception) -> bool:
    return "429" in str(exc) or "too many requests" in str(exc).lower()


def _status_key(user_id: str) -> str:
    return f"poller_status:{user_id}"


async def get_user_poller_status(user_id: str) -> dict:
    """Returns the last recorded Garmin poll status for a user from Redis."""
    redis = await get_redis_client()
    raw = await redis.get(_status_key(str(user_id)))
    if not raw:
        return {"last_poll_at": None, "last_error": None, "error_count": 0, "metrics_count": 0}
    return json.loads(raw)


async def _update_poller_status(user_id: str, **fields) -> None:
    """Merges the given fields into the user's poller status entry in Redis."""
    redis = await get_redis_client()
    status = await get_user_poller_status(user_id)
    status.update(fields)
    await redis.set(_status_key(str(user_id)), json.dumps(status))


async def run_poll_cycle(user_id: str, email: str, password_encrypted: str) -> dict:
    """Runs a single Garmin fetch-and-publish cycle for a user, recording the outcome in Redis."""
    try:
        password = settings.decrypt_value(password_encrypted)
    except Exception as e:
        logger.error(f"AES decryption failed for user {user_id} Garmin credentials: {e}")
        await _update_poller_status(user_id, last_error=f"Credential decryption failed: {e}")
        return {"ok": False, "error": f"Credential decryption failed: {e}"}

    client = AsyncGarminClient(email, password, user_id=user_id)

    try:
        logger.info(f"Poller [User {user_id}]: Fetching data from Garmin API...")
        metrics = await client.fetch_all_metrics()
    except Exception as e:
        status = await get_user_poller_status(user_id)
        if _is_rate_limited(e):
            logger.warning(f"Poller [User {user_id}]: rate-limited (429) — {e}")
        else:
            logger.error(f"Poller [User {user_id}]: fetch failed — {e}", exc_info=True)
        await _update_poller_status(
            user_id,
            last_error=str(e),
            error_count=status.get("error_count", 0) + 1,
        )
        return {"ok": False, "error": str(e)}

    recorded_at = datetime.now(timezone.utc).isoformat()
    published = 0
    for metric, value in metrics.items():
        if value is not None:
            try:
                await publish_metric(
                    user_id=user_id,
                    metric=metric,
                    value=value,
                    recorded_at=recorded_at,
                    source="garmin"
                )
                published += 1
            except Exception as e:
                logger.error(f"Poller [User {user_id}]: failed to publish metric '{metric}': {e}")

    await _update_poller_status(
        user_id,
        last_poll_at=recorded_at,
        last_error=None,
        error_count=0,
        metrics_count=published,
    )
    logger.info(f"Poller [User {user_id}]: published {published} metrics.")
    return {"ok": True, "published": published, "recorded_at": recorded_at}


async def manual_poll_user(user_id: str, email: str, password_encrypted: str) -> dict:
    """Runs a single poll cycle immediately for the given user (used by the manual /health/poll endpoint)."""
    return await run_poll_cycle(user_id, email, password_encrypted)
