"""
Consolidated Chatbot Orchestration Router
All chatbot orchestration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from typing import Dict, List, Any, Optional
import logging
from shared.otel_logger import get_otel_logger

from ..service.chat_service import ChatService
from ..service.agent_service import PydanticAIGatewayService
from ..schemas.models import ChatRequest
from ..dao.session_persistence_dao import SessionPersistenceDAO

logger = get_otel_logger(__name__, "chatbot-orchestration")
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

        # If no session_id provided, create one via PG18 UUIDv7
        is_new_session = not session_id
        if not session_id:
            from chatbot_orchestration.dao.session_persistence_dao import SessionPersistenceDAO
            session_dao = SessionPersistenceDAO()
            session_id = await session_dao.create_session()
            logger.info(f"✅ Created new PG18 UUIDv7 session: {session_id}")
        else:
            # Ensure existing session is in both Redis and PG
            try:
                from chatbot_orchestration.dao.session_persistence_dao import SessionPersistenceDAO
                session_dao = SessionPersistenceDAO()
                await session_dao.ensure_session(session_id)
                logger.info(f"✅ Session {session_id} ensured in database")
            except Exception as e:
                logger.error(f"⚠️ Failed to ensure session in database: {e}")

        # Build response headers
        response_headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }

        # For new sessions, prepend session UUID in first SSE event
        async def generate_response_with_session():
            # If new session, send session UUID as first event
            if is_new_session:
                import json
                session_event = json.dumps({"type": "session_created", "session_id": session_id})
                yield f"data: {session_event}\n\n"
                logger.info(f"📋 Sent session_created event with UUID: {session_id}")
            
            # Then stream the actual response
            chunk_counter = 0
            async for chunk in agent_service.stream_agent_response(message, session_id):
                chunk_counter += 1
                logger.info(f"🔍 [YIELD-DEBUG] Yielding chunk #{chunk_counter} for session {session_id}")
                yield chunk

        return StreamingResponse(
            generate_response_with_session(),
            media_type="text/event-stream",
            headers=response_headers
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
    """Create a new chat session with PG18 UUIDv7"""
    try:
        body = await request.json()

        agent_id = body.get("agent_id", "default")

        from chatbot_orchestration.dao.session_persistence_dao import SessionPersistenceDAO
        session_dao = SessionPersistenceDAO()
        session_id = await session_dao.create_session()

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
# INTERNAL ENDPOINTS (ADMIN ONLY)
# =================================

@router.post("/internal/clear-agent-cache")
async def clear_agent_cache(request: Request):
    """Clear agent cache when configuration changes.

    Called by configuration service when chatbot config is saved.
    This ensures the next message will use the updated configuration.
    """
    try:
        from ..service.agent_manager import agent_manager

        # Get optional session_id from query params
        session_id = request.query_params.get("session_id", None)

        if session_id:
            logger.info(f"Clearing agent cache for session: {session_id}")
            await agent_manager.clear_agent_cache(session_id)
            return {
                "success": True,
                "message": f"Agent cache cleared for session: {session_id}"
            }
        else:
            logger.info("Clearing all agent caches")
            await agent_manager.clear_agent_cache()
            return {
                "success": True,
                "message": "All agent caches cleared"
            }
    except Exception as e:
        logger.error(f"❌ Error clearing agent cache: {e}")
        raise HTTPException(status_code=500, detail=f"Error clearing agent cache: {str(e)}")

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
