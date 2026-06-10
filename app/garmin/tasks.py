import asyncio
import logging
import random

from sqlalchemy import select

from app.celery_app import celery_app
from app.db.session import async_engine, async_session_factory
from app.garmin.poller import run_poll_cycle
from app.kafka.producer import close_kafka_producer
from app.models.db_models import User
from app.redis.client import close_redis

logger = logging.getLogger(__name__)


async def _run_and_cleanup(coro):
    """Awaits a coroutine, then disposes the per-process Redis/Kafka/DB clients.

    Each Celery task runs inside its own asyncio.run() (a fresh event loop), and
    aioredis/aiokafka/asyncpg connections are bound to the loop they were created
    on, so they must not be reused across invocations.
    """
    try:
        return await coro
    finally:
        await close_redis()
        await close_kafka_producer()
        await async_engine.dispose()


@celery_app.task(name="app.garmin.tasks.poll_user_task")
def poll_user_task(user_id: str, email: str, password_encrypted: str) -> dict:
    """Runs one Garmin fetch-and-publish cycle for a single user."""
    return asyncio.run(_run_and_cleanup(run_poll_cycle(user_id, email, password_encrypted)))


@celery_app.task(name="app.garmin.tasks.poll_all_users_task")
def poll_all_users_task() -> int:
    """Beat-scheduled task: dispatches a poll task for every user with Garmin credentials configured."""

    async def _load_users():
        async with async_session_factory() as session:
            result = await session.execute(
                select(User).where(
                    User.garmin_username.isnot(None),
                    User.garmin_password_encrypted.isnot(None),
                )
            )
            return [
                (str(u.id), u.garmin_username, u.garmin_password_encrypted)
                for u in result.scalars().all()
            ]

    users = asyncio.run(_run_and_cleanup(_load_users()))

    for user_id, email, password_encrypted in users:
        # Stagger dispatch to avoid a thundering herd against the Garmin API
        poll_user_task.apply_async(
            args=[user_id, email, password_encrypted],
            countdown=random.uniform(0, 30),
        )

    logger.info(f"Dispatched Garmin poll tasks for {len(users)} users.")
    return len(users)
