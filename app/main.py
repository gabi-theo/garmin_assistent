import asyncio
import logging
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.init import init_db
from app.redis.client import init_redis, close_redis
from app.redis.cache import start_cache_flusher
from app.kafka.producer import init_kafka_producer, close_kafka_producer
from app.kafka.consumer import start_kafka_consumer, stop_kafka_consumer

from app.api.auth import router as auth_router
from app.api.metrics import router as metrics_router
from app.api.insights import router as insights_router
from app.api.chat import router as chat_router
from app.api.ws import router as ws_router
from app.api.health import router as health_router

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Global storage for background tasks
_cache_flusher_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cache_flusher_task
    logger.info("Initializing health analytics platform...")

    # 1. Setup Postgres schemas & TimescaleDB Hypertables
    try:
        await init_db()
    except Exception as e:
        logger.fatal(f"Database schema initialization failed: {e}", exc_info=True)
        raise e

    # 2. Setup Redis pool
    await init_redis()

    # 3. Launch the background 60s Cache Persistor task
    _cache_flusher_task = asyncio.create_task(start_cache_flusher())

    # 4. Start Kafka Producer
    await init_kafka_producer()

    # 5. Start Kafka Consumer Loop
    await start_kafka_consumer()

    logger.info("Platform startup sequence completed successfully.")

    yield

    logger.info("Initiating platform shutdown sequence...")

    # 1. Cancel and stop Kafka consumer task
    await stop_kafka_consumer()

    # 2. Shutdown Kafka producer client
    await close_kafka_producer()

    # 3. Terminate background cache flusher task
    if _cache_flusher_task:
        logger.info("Stopping cache flusher task...")
        _cache_flusher_task.cancel()
        try:
            await _cache_flusher_task
        except asyncio.CancelledError:
            pass
        logger.info("Cache flusher task stopped.")

    # 4. Close Redis client connection pool
    await close_redis()

    logger.info("Platform shutdown completed.")


app = FastAPI(
    title="Async Health Analytics Platform",
    description="Production-grade asynchronous biometric analytics platform with Garmin polling, Kafka, Redis, and LangGraph",
    version="1.0.0",
    lifespan=lifespan
)

# Apply CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount endpoints
app.include_router(auth_router)
app.include_router(metrics_router)
app.include_router(insights_router)
app.include_router(chat_router)
app.include_router(ws_router)
app.include_router(health_router)


@app.get("/")
async def read_root():
    """Root status check endpoint."""
    return {
        "status": "online",
        "service": "Async Health Analytics Engine",
        "version": "1.0.0"
    }
