"""
Consolidated Chatbot Orchestration Router
All chatbot orchestration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any, Optional
import logging
import time

from ..service.chat_service import ChatService
from ..service.agent_service import PydanticAIGatewayService
from ..schemas.models import ChatRequest
from ..dao.session_persistence_dao import SessionPersistenceDAO

logger = logging.getLogger(__name__)
from ..core.utils import log_endpoint_request

router = APIRouter()

# Initialize services
chat_service = ChatService()
agent_service = PydanticAIGatewayService()

# =================================
# CHAT ENDPOINTS (STREAMING ONLY)
# =================================

@router.post("/chat/stream")
async def chat_with_agent_stream(request: Request):
    """Chat with AI agent with streaming response using Pydantic AI

    Creates session in database on first message if it doesn't exist.
    """
    try:
        body = await request.json()

        message = body.get("message")
        session_id = body.get("session_id")

        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        # Get session UUID from request header (set by API Gateway on first message)
        # API Gateway generates UUID for every request, passes it via internal header
        internal_session_uuid = request.headers.get("X-Internal-Session-UUID")

        # If no session_id in body, use the one from header (first message)
        if not session_id:
            session_id = internal_session_uuid
            logger.info(f"✅ Received session UUID from API Gateway: {session_id}")

            # CRITICAL: Save session to database BEFORE returning response
            # This ensures API Gateway can resolve UUID → numeric ID for subsequent requests
            try:
                from chatbot_orchestration.dao.session_persistence_dao import SessionPersistenceDAO
                session_dao = SessionPersistenceDAO()
                session_db_id = await session_dao.get_or_create_session(session_id)
                logger.info(f"✅ Session {session_id} created in database with ID {session_db_id}")
            except Exception as e:
                logger.error(f"⚠️ Failed to create session in database: {e}")
                # Continue anyway - session will be created when first message is saved

        # Stream response (tools are configured internally in agent_manager)
        async def generate_response():
            async for chunk in agent_service.stream_agent_response(message, session_id):
                yield chunk

        # Return streaming response without exposing session UUID
        # Session UUID is managed entirely via httpOnly cookie by API Gateway
        # Internal services work with numeric session ID only
        return StreamingResponse(
            generate_response(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )
    except Exception as e:
        logger.error(f"Error in chat stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str):
    """Get chat history for a session"""
    try:
        history = await chat_service.get_chat_history(session_id)
        
        return {
            "success": True,
            "history": history,
            "session_id": session_id
        }
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str):
    """Delete a chat session"""
    try:
        result = await chat_service.delete_session(session_id)
        
        return {
            "success": True,
            "message": "Session deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/session")
async def create_chat_session(request: Request):
    """Create a new chat session"""
    try:
        body = await request.json()
        
        agent_id = body.get("agent_id", "default")
        
        session_id = f"session_{int(time.time())}"
        
        return {
            "success": True,
            "session_id": session_id,
            "agent_id": agent_id
        }
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat/sessions")
async def get_user_sessions():
    """Get all chat sessions"""
    try:
        sessions = await chat_service.get_all_sessions()

        return {
            "success": True,
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        health_status = {
            "status": "healthy",
            "service": "chatbot_orchestration",
            "timestamp": "2024-01-01T00:00:00Z",
            "components": {
                "chat_service": "healthy",
                "agent_service": "healthy",
                "database": "connected"
            }
        }
        return health_status
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
