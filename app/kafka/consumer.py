import asyncio
import json
import logging
import uuid
from typing import Optional
from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.agent.graph import agent_graph
from app.redis.locks import acquire_lock, release_lock
from app.redis.cache import cache_metric

logger = logging.getLogger(__name__)

# Track active consumer tasks
_consumer_task: Optional[asyncio.Task] = None


async def start_kafka_consumer() -> None:
    """Starts the Kafka consumer loop in the background."""
    global _consumer_task
    if _consumer_task is None:
        logger.info("Launching Kafka consumer task...")
        _consumer_task = asyncio.create_task(kafka_consumer_loop())


async def stop_kafka_consumer() -> None:
    """Cancels and cleans up the Kafka consumer task."""
    global _consumer_task
    if _consumer_task is not None:
        logger.info("Stopping Kafka consumer task...")
        _consumer_task.cancel()
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
        _consumer_task = None
        logger.info("Kafka consumer task stopped.")


async def kafka_consumer_loop() -> None:
    """Subscribes to all garmin telemetry topics and executes the ingestion pipeline."""
    logger.info("Starting background AIOKafkaConsumer connection...")
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="health-analytics-ingest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest"
    )
    
    # Subscribe to any topic starting with 'garmin.'
    consumer.subscribe(pattern="^garmin\\..*")
    await consumer.start()
    logger.info("Kafka consumer subscribed to topic pattern '^garmin\\..*'")

    try:
        async for msg in consumer:
            payload = msg.value
            logger.info(f"Received telemetry event from Kafka topic '{msg.topic}'")
            
            user_id = payload.get("user_id")
            metric = payload.get("metric")
            value = payload.get("value")
            recorded_at = payload.get("recorded_at")
            source = payload.get("source", "garmin")

            if not user_id or not metric:
                logger.warning(f"Skipping malformed Kafka payload: {payload}")
                continue

            lock_key = f"lock:agent:{user_id}"
            lock_id = str(uuid.uuid4())

            # 1. Acquire distributed lock for the user (30s timeout)
            acquired = await acquire_lock(lock_key, lock_id, ttl_seconds=30)
            if not acquired:
                logger.warning(
                    f"Lock active for user {user_id}. "
                    "Skipping duplicate message to prevent race conditions."
                )
                continue

            try:
                # 2. Write-through cache write (Sorted Set & Persist Queue)
                await cache_metric(
                    user_id=user_id,
                    metric=metric,
                    value=value,
                    recorded_at=recorded_at,
                    source=source
                )

                # 3. Initialize LangGraph state
                initial_state = {
                    "user_id": user_id,
                    "metric": metric,
                    "latest_value": value,
                    "recorded_at": recorded_at,
                    "history": [],
                    "anomaly_detected": False,
                    "deviation_pct": None,
                    "insight": None,
                    "chat_mode": False,
                    "chat_question": None,
                    "error": None
                }

                # 4. Invoke the reasoning agent
                logger.info(f"Triggering LangGraph agent for user {user_id} on {metric}")
                await agent_graph.ainvoke(
                    initial_state,
                    config={"configurable": {"lock_identifier": lock_id}}
                )

            except Exception as e:
                logger.error(f"Error processing telemetry for user {user_id}: {e}", exc_info=True)
            finally:
                # 5. Guarantee lock release using the owner identifier
                # (If persist_results already deleted it, this is an idempotent no-op)
                await release_lock(lock_key, lock_id)

    except asyncio.CancelledError:
        logger.info("Kafka consumer loop cancelled.")
    except Exception as e:
        logger.error(f"Fatal error in Kafka consumer loop: {e}", exc_info=True)
    finally:
        logger.info("Shutting down Kafka consumer client...")
        await consumer.stop()
