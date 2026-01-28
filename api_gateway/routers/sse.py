import time

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api_gateway.core.config import CONFIGURATION_SERVICE_URL
from api_gateway.core.sse import sse_generator, sse_manager
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

router = APIRouter()

@router.get("/ws/events")
async def websocket_sse_endpoint():
    """SSE endpoint to replace WebSocket functionality."""
    queue = await sse_manager.connect()
    
    try:
        return StreamingResponse(
            sse_generator(queue),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
    except Exception as e:
        logger.error(f"SSE endpoint error: {e}")
        await sse_manager.disconnect(queue)
        raise HTTPException(status_code=500, detail="SSE connection failed")

@router.post("/ws/messages")
async def websocket_message_endpoint(request: Request):
    """HTTP endpoint to receive messages and broadcast via SSE."""
    try:
        data = await request.json()
        
        message = {
            "type": "response",
            "message": data.get("message", ""),
            "conversation_id": data.get("conversation_id", ""),
            "timestamp": time.time(),
            "metadata": data.get("metadata", {})
        }
        
        await sse_manager.broadcast(message)
        
        return {"success": True, "message": "Message broadcasted"}
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail="Failed to process message")

@router.get("/api/v1/chat/{session_id}/events")
async def proxy_customer_sse(session_id: str, request: Request):
    """Proxy customer SSE connections to configuration service"""
    try:
        sse_url = f"{CONFIGURATION_SERVICE_URL}/api/v1/chat/{session_id}/events"

        async with httpx.AsyncClient(timeout=300.0) as client:
            headers = dict(request.headers)
            headers.pop("host", None)

            response = await client.get(
                sse_url,
                headers=headers,
                params=request.query_params
            )
            
            return StreamingResponse(
                response.aiter_bytes(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": response.headers.get("Cache-Control", "no-cache"),
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                }
            )

    except Exception as e:
        logger.error(f"❌ SSE proxy error: {e}")
        raise HTTPException(status_code=500, detail="SSE proxy error")

@router.get("/api/v1/admin/chat-sessions/{session_id}/events")
async def proxy_agent_sse(session_id: str, request: Request):
    """Proxy agent SSE connections to configuration service"""
    try:
        sse_url = f"{CONFIGURATION_SERVICE_URL}/api/v1/admin/chat-sessions/{session_id}/events"

        async with httpx.AsyncClient(timeout=300.0) as client:
            headers = dict(request.headers)
            headers.pop("host", None)

            response = await client.get(
                sse_url,
                headers=headers,
                params=request.query_params
            )

            return StreamingResponse(
                response.aiter_bytes(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": response.headers.get("Cache-Control", "no-cache"),
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                }
            )

    except Exception as e:
        logger.error(f"SSE proxy error: {e}")
        raise HTTPException(status_code=500, detail="SSE proxy error")
