import json
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from app.redis.client import get_redis_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSockets"])


@router.websocket("/live")
async def websocket_live_updates(
    websocket: WebSocket,
    token: str = Query(..., description="Active session authentication token")
):
    """WebSocket endpoint to push live biometric insights and alerts to authenticated users."""
    await websocket.accept()

    redis = await get_redis_client()
    session_key = f"session:{token}"
    session_data = await redis.get(session_key)

    if not session_data:
        logger.warning("WebSocket connection rejected: Invalid session token.")
        await websocket.close(code=4001)  # Policy violation close code
        return

    # Extract user ID from session data (handles both JSON and raw string)
    try:
        user_info = json.loads(session_data)
        user_id = user_info["id"]
    except Exception:
        user_id = session_data

    logger.info(f"WebSocket client connected: User ID {user_id}")

    pubsub = redis.pubsub()
    channel = f"live:{user_id}"
    await pubsub.subscribe(channel)
    logger.info(f"Subscribed WebSocket connection to Redis channel '{channel}'")

    # Read loop to detect client disconnection
    async def listen_for_disconnect():
        try:
            while True:
                # Wait for any message (which we ignore) or client disconnect
                await websocket.receive_text()
        except WebSocketDisconnect:
            logger.info(f"Client disconnected socket for User {user_id}")

    disconnect_task = asyncio.create_task(listen_for_disconnect())

    try:
        while not disconnect_task.done():
            # Retrieve message from channel (ignores setup subscriptions, 1.0s wait)
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if message:
                payload = message["data"]
                await websocket.send_text(payload)
                
            await asyncio.sleep(0.05)  # Yield control to event loop

    except Exception as e:
        logger.error(f"WebSocket session exception for user {user_id}: {e}", exc_info=True)
    finally:
        # Cleanup tasks and subscriptions
        disconnect_task.cancel()
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception as e:
            logger.warning(f"Error closing Redis pub/sub during socket cleanup: {e}")
        
        logger.info(f"WebSocket cleanup complete for user {user_id}.")
        # Ensure socket is closed
        try:
            await websocket.close()
        except Exception:
            pass
