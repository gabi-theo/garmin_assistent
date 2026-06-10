import logging
from sqlalchemy import text
from app.db.session import async_engine
from app.models.db_models import Base

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Creates the base tables and converts them to TimescaleDB hypertables if needed."""
    logger.info("Initializing database schemas...")
    
    # 1. Create standard tables via SQLAlchemy Metadata
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("SQLAlchemy base tables created.")

    # 2. Convert to TimescaleDB Hypertables (requires separate transaction block)
    async with async_engine.connect() as conn:
        try:
            # Enable TimescaleDB extension
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
            
            # Check and create hypertable for metrics table
            await conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM _timescaledb_catalog.hypertable 
                        WHERE table_name = 'metrics'
                    ) THEN
                        PERFORM create_hypertable('metrics', 'time');
                    END IF;
                END $$;
            """))
            
            # Check and create hypertable for profile_snapshots table
            await conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM _timescaledb_catalog.hypertable 
                        WHERE table_name = 'profile_snapshots'
                    ) THEN
                        PERFORM create_hypertable('profile_snapshots', 'time');
                    END IF;
                END $$;
            """))

            # Create standard index for user metrics time series queries
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_metrics_user_metric_time "
                "ON metrics (user_id, metric, time DESC);"
            ))
            
            await conn.commit()
            logger.info("TimescaleDB hypertables and indexes initialized successfully.")
        except Exception as e:
            logger.error(f"Error setting up TimescaleDB hypertables: {e}")
            await conn.rollback()
            raise e
