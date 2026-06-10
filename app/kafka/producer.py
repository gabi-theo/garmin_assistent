import json
import logging
from typing import Any, Optional
from aiokafka import AIOKafkaProducer

from app.config import settings

logger = logging.getLogger(__name__)

# Single global Kafka producer instance
_kafka_producer: Optional[AIOKafkaProducer] = None


async def init_kafka_producer() -> AIOKafkaProducer:
    """Initializes and starts the async Kafka producer."""
    global _kafka_producer
    if _kafka_producer is None:
        logger.info(f"Connecting to Kafka brokers at {settings.KAFKA_BOOTSTRAP_SERVERS}...")
        _kafka_producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8")
        )
        await _kafka_producer.start()
        logger.info("Kafka producer started successfully.")
    return _kafka_producer


async def get_kafka_producer() -> AIOKafkaProducer:
    """Returns the active global Kafka producer instance."""
    global _kafka_producer
    if _kafka_producer is None:
        await init_kafka_producer()
    assert _kafka_producer is not None
    return _kafka_producer


async def close_kafka_producer() -> None:
    """Stops and closes the Kafka producer connection."""
    global _kafka_producer
    if _kafka_producer is not None:
        logger.info("Stopping Kafka producer...")
        await _kafka_producer.stop()
        _kafka_producer = None
        logger.info("Kafka producer stopped.")


async def publish_metric(
    user_id: str,
    metric: str,
    value: Any,
    recorded_at: str,
    source: str = "garmin"
) -> None:
    """Publishes a telemetry metric message to a Kafka topic."""
    producer = await get_kafka_producer()
    topic = f"garmin.{metric}.{user_id}"
    payload = {
        "user_id": user_id,
        "metric": metric,
        "value": value,
        "recorded_at": recorded_at,
        "source": source
    }
    
    try:
        # Publish asynchronously and wait for broker confirmation
        await producer.send_and_wait(topic, payload)
        logger.debug(f"Successfully published metric '{metric}' to topic '{topic}'")
    except Exception as e:
        logger.error(f"Failed to publish metric to Kafka on topic {topic}: {e}")
        raise e
