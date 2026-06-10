import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.models.schemas import ChatRequest
from app.agent.graph import agent_graph
from app.api.deps import get_current_user, AuthenticatedUser, rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"], dependencies=[rate_limit])


@router.post("", response_class=EventSourceResponse)
async def chat_with_agent(
    payload: ChatRequest,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Interacts with the LangGraph agent in chat mode. Streams responses over SSE."""
    logger.info(f"Chat request received from user {current_user.id} on metric '{payload.metric}'")

    token_queue = asyncio.Queue()

    # Callback to feed LLM token stream into the queue
    async def token_callback(token: str) -> None:
        await token_queue.put(token)

    # Initialize graph state for chat mode
    initial_state = {
        "user_id": current_user.id,
        "metric": payload.metric,
        "latest_value": 0.0,  # Dummy value, bypassed by chat mode entry routing
        "recorded_at": datetime.now(timezone.utc).isoformat() + "Z",
        "history": [],
        "anomaly_detected": False,
        "deviation_pct": None,
        "insight": None,
        "chat_mode": True,  # Flags entry routing in agent/graph.py
        "chat_question": payload.question,
        "error": None
    }

    # Execute graph inside an asynchronous task
    config = {"configurable": {"token_callback": token_callback}}
    graph_run_task = asyncio.create_task(agent_graph.ainvoke(initial_state, config=config))

    async def sse_event_generator():
        try:
            while not graph_run_task.done() or not token_queue.empty():
                try:
                    # Non-blocking pop with short timeout to allow loop health check
                    token = await asyncio.wait_for(token_queue.get(), timeout=0.2)
                    yield {"event": "message", "data": token}
                    token_queue.task_done()
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in SSE generator queue fetch: {e}")
                    yield {"event": "error", "data": f"Stream error: {str(e)}"}
                    break

            # Handle post-execution checks
            if graph_run_task.done() and graph_run_task.exception():
                exc = graph_run_task.exception()
                logger.error(f"LangGraph execution crashed: {exc}")
                yield {"event": "error", "data": f"Agent graph error: {str(exc)}"}
            else:
                logger.info(f"Successfully finished chat stream for user {current_user.id}")
                yield {"event": "done", "data": "[DONE]"}

        except asyncio.CancelledError:
            logger.warning(f"SSE client disconnected. Cancelling agent execution...")
            graph_run_task.cancel()
            raise

    return EventSourceResponse(sse_event_generator())
