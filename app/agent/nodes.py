import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy import select
from langchain_community.llms import Ollama
from langchain_core.runnables import RunnableConfig

from app.config import settings
from app.agent.state import AgentState
from app.db.session import async_session_factory
from app.models.db_models import Metric as DBMetric, Insight as DBInsight, ProfileSnapshot
from app.redis.client import get_redis_client
from app.redis.locks import release_lock

logger = logging.getLogger(__name__)


def get_numeric_value(val: Any) -> Optional[float]:
    """Extract a float representation from a metric value (float or dict)."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        # Check common keys for numeric metric values in Garmin data
        for key in ["value", "score", "average", "hrv", "duration", "steps", "stress_level", "vo2max"]:
            if key in val and isinstance(val[key], (int, float)):
                return float(val[key])
    return None


async def ingest_metrics(state: AgentState) -> AgentState:
    """Normalizes the Kafka payload and validates the input schema."""
    logger.info(f"Node [ingest_metrics]: Ingesting metric {state.get('metric')} for user {state.get('user_id')}")
    
    # Simple validation of required state parameters
    if not state.get("user_id") or not state.get("metric"):
        state["error"] = "Missing user_id or metric in state payload"
        return state

    # Parse and format recorded_at
    recorded_at = state.get("recorded_at")
    if not recorded_at:
        state["recorded_at"] = datetime.now(timezone.utc).isoformat()
    
    # Ensure latest_value is present
    if "latest_value" not in state:
        state["error"] = "Missing latest_value in telemetry payload"
        
    return state


async def detect_anomaly(state: AgentState) -> AgentState:
    """Computes rolling statistics over the last 7 days from Redis and flags anomalies."""
    logger.info(f"Node [detect_anomaly]: Checking anomaly for user {state['user_id']} metric {state['metric']}")
    
    latest_numeric = get_numeric_value(state["latest_value"])
    if latest_numeric is None:
        state["anomaly_detected"] = False
        state["deviation_pct"] = 0.0
        return state

    redis = await get_redis_client()
    key = f"metrics:{state['user_id']}:{state['metric']}"

    # Get last 7 days of metrics from Redis
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)
    min_score = seven_days_ago.timestamp()
    max_score = now.timestamp()

    # Fetch elements from sorted set
    raw_elements = await redis.zrangebyscore(key, min_score, max_score)
    
    values = []
    for elem in raw_elements:
        try:
            data = json.loads(elem)
            val = get_numeric_value(data.get("value"))
            if val is not None:
                values.append(val)
        except Exception as e:
            logger.error(f"Error parsing cached metric element: {e}")

    # Add the current value to list if not already cached
    values.append(latest_numeric)

    if len(values) < 3:
        # Not enough history to compute meaningful rolling deviation
        state["anomaly_detected"] = False
        state["deviation_pct"] = 0.0
        return state

    # Compute mean and standard deviation
    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std_dev = variance ** 0.5

    # Check deviation threshold (> 1.5 standard deviations)
    deviation = abs(latest_numeric - mean)
    threshold = 1.5 * std_dev
    
    state["anomaly_detected"] = deviation > threshold and std_dev > 0.0
    state["deviation_pct"] = round(((latest_numeric - mean) / mean) * 100.0, 2) if mean != 0 else 0.0
    
    logger.info(
        f"Anomaly analysis complete. Mean: {mean:.2f}, StdDev: {std_dev:.2f}, "
        f"Latest: {latest_numeric:.2f}, Anomaly: {state['anomaly_detected']}"
    )
    return state


async def retrieve_history(state: AgentState) -> AgentState:
    """Pulls the last 20 data points from Redis; backfills from TimescaleDB if needed."""
    logger.info(f"Node [retrieve_history]: Fetching telemetry context for user {state['user_id']}")
    
    user_id = state["user_id"]
    metric = state["metric"]
    
    redis = await get_redis_client()
    key = f"metrics:{user_id}:{metric}"

    # Fetch newest 20 elements from Redis sorted set
    # ZREVRANGE fetches highest scores (newest) first
    raw_redis_data = await redis.zrevrange(key, 0, 19)
    
    history_list = []
    for item in raw_redis_data:
        try:
            history_list.append(json.loads(item))
        except Exception as e:
            logger.error(f"Error parsing redis item in retrieve_history: {e}")

    # Reverse to list chronologically (oldest -> newest)
    history_list.reverse()

    # If cache has fewer than 20 points, query TimescaleDB to backfill
    if len(history_list) < 20:
        logger.info(f"Cache hit insufficient ({len(history_list)} points). Backfilling from TimescaleDB.")
        backfill_limit = 20 - len(history_list)
        
        async with async_session_factory() as session:
            query = (
                select(DBMetric)
                .where(DBMetric.user_id == user_id, DBMetric.metric == metric)
                .order_by(DBMetric.time.desc())
                .limit(backfill_limit)
            )
            result = await session.execute(query)
            db_metrics = result.scalars().all()
            
            # Format and prepend to history list
            db_history = [
                {"value": db_m.value, "recorded_at": db_m.time.isoformat(), "source": "garmin"}
                for db_m in db_metrics
            ]
            # Reverse db history to match chronological order (oldest -> newest)
            db_history.reverse()
            history_list = db_history + history_list

    # Ensure uniqueness based on recorded_at timestamp and sort oldest -> newest
    unique_history = {}
    for item in history_list:
        recorded_at = item.get("recorded_at")
        if recorded_at:
            unique_history[recorded_at] = item
            
    sorted_history = [unique_history[k] for k in sorted(unique_history.keys())]
    state["history"] = sorted_history[-20:] # Keep exactly the last 20 points
    
    return state


async def generate_insight(state: AgentState, config: Optional[RunnableConfig] = None) -> AgentState:
    """Calls Ollama to generate a structured metric insight (supports streaming callback)."""
    logger.info(f"Node [generate_insight]: Running LLM reasoning graph for user {state['user_id']}")
    
    # Configure Ollama instance
    llm = Ollama(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.OLLAMA_MODEL,
    )

    # Format historical metrics for context
    history_context = []
    for pt in state.get("history", []):
        history_context.append(f"{pt.get('recorded_at')}: {pt.get('value')}")
    
    history_str = "\n".join(history_context)

    # Build prompt
    prompt = (
        "You are a personal fitness and recovery coach with expertise in biometric data.\n"
        "Given the following data, identify any concerns and provide a concise, specific,\n"
        "actionable recommendation in 2-3 sentences. Reference the actual numbers.\n\n"
        f"Metric: {state['metric']}\n"
        f"Recent values (oldest → newest):\n{history_str}\n"
        f"Anomaly detected: {state.get('anomaly_detected', False)}\n"
        f"Deviation from 7-day average: {state.get('deviation_pct', 0.0)}%\n\n"
    )

    if state.get("chat_mode", False):
        prompt += f"If in chat mode, also answer this question from the user: {state.get('chat_question')}\n"
    else:
        prompt += "Provide your general recovery insight coaching recommendation now.\n"

    # Streaming callback setup
    configurable = (config or {}).get("configurable", {})
    token_callback = configurable.get("token_callback")

    insight_chunks = []
    try:
        async for chunk in llm.astream(prompt):
            insight_chunks.append(chunk)
            if token_callback:
                # Forward chunk to SSE listener
                await token_callback(chunk)
        
        state["insight"] = "".join(insight_chunks).strip()
    except Exception as e:
        logger.error(f"Error calling Ollama LLM: {e}")
        state["error"] = f"LLM generation error: {str(e)}"
        state["insight"] = None  # don't persist an error string as a real insight
        if token_callback:
            await token_callback("[Ollama unavailable — pull the model with: ollama pull llama3]")

    return state


async def persist_results(state: AgentState) -> AgentState:
    """Writes the generated insight to TimescaleDB, updates user profile, and pushes to WebSockets."""
    logger.info(f"Node [persist_results]: Saving agent outputs for user {state['user_id']}")
    
    user_id = state["user_id"]
    metric = state["metric"]
    insight = state.get("insight")
    
    # If no insight was generated (e.g. no anomaly detected, and not in chat mode), skip saving insight
    async with async_session_factory() as session:
        # Write to Insights Table if an insight was generated
        if insight:
            db_insight = DBInsight(
                user_id=user_id,
                metric=metric,
                insight=insight,
                anomaly_detected=state.get("anomaly_detected", False),
                deviation_pct=state.get("deviation_pct")
            )
            session.add(db_insight)

        # Update profile snapshot
        # 1. Fetch most recent snapshot
        last_snapshot_query = (
            select(ProfileSnapshot)
            .where(ProfileSnapshot.user_id == user_id)
            .order_by(ProfileSnapshot.time.desc())
            .limit(1)
        )
        snapshot_result = await session.execute(last_snapshot_query)
        last_snapshot = snapshot_result.scalar_one_or_none()

        # 2. Determine scores based on metric values
        fatigue_score = last_snapshot.fatigue_score if last_snapshot else 50.0
        recovery_score = last_snapshot.recovery_score if last_snapshot else 50.0
        
        latest_numeric = get_numeric_value(state["latest_value"])
        if latest_numeric is not None:
            if metric == "stress":
                # Stress increases fatigue (stress is normally 0-100)
                fatigue_score = min(100.0, max(0.0, latest_numeric))
            elif metric == "activity":
                # Activity spikes fatigue
                fatigue_score = min(100.0, fatigue_score + 15.0)
            elif metric == "hrv":
                # HRV increases recovery score
                # Normal resting HRV could be 30-100, let's normalize to a score
                recovery_score = min(100.0, max(0.0, latest_numeric))
            elif metric == "sleep":
                # Sleep increases recovery score
                # If sleep value is a dictionary containing sleep score
                sleep_score = latest_numeric
                if isinstance(state["latest_value"], dict) and "score" in state["latest_value"]:
                    sleep_score = float(state["latest_value"]["score"])
                recovery_score = min(100.0, max(0.0, sleep_score))

        # 3. Save new snapshot
        new_snapshot = ProfileSnapshot(
            time=datetime.now(timezone.utc),
            user_id=user_id,
            fatigue_score=round(fatigue_score, 2),
            recovery_score=round(recovery_score, 2),
            notes=insight or f"Telemetry sync for {metric}"
        )
        session.add(new_snapshot)
        await session.commit()

        # Publish updates to Redis Pub/Sub live channel
        redis = await get_redis_client()
        pubsub_channel = f"live:{user_id}"
        event_payload = {
            "type": "insight_alert" if state.get("anomaly_detected") else "metric_update",
            "user_id": user_id,
            "metric": metric,
            "value": state["latest_value"],
            "insight": insight,
            "anomaly_detected": state.get("anomaly_detected", False),
            "deviation_pct": state.get("deviation_pct"),
            "fatigue_score": fatigue_score,
            "recovery_score": recovery_score,
            "recorded_at": state["recorded_at"]
        }
        await redis.publish(pubsub_channel, json.dumps(event_payload))
        logger.info(f"Published telemetry event to channel {pubsub_channel}")

    # Release distributed lock
    lock_key = f"lock:agent:{user_id}"
    await release_lock(lock_key)
    logger.info(f"Released agent lock: {lock_key}")
    
    return state
