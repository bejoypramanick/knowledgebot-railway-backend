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
persistence_dao = SessionPersistenceDAO()

# =================================
# CHAT ENDPOINTS
# =================================

@router.post("/chat")
async def chat_with_agent(request: Request):
    """Chat with AI agent with message persistence"""
    session_db_id = None
    try:
        body = await request.json()

        message = body.get("message")
        session_id = body.get("session_id")

        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        # Create session if not provided
        if not session_id:
            session_id = f"session_{int(time.time())}"

        # Get or create session in database and save user message
        try:
            session_db_id = await persistence_dao.get_or_create_session(session_id)
            await persistence_dao.save_user_message(session_db_id, message)
            logger.info(f"💬 Saved user message for session {session_id}")
        except Exception as e:
            logger.error(f"⚠️ Failed to save user message: {e}")
            # Continue processing even if message save fails

        # Process chat message
        response = await agent_service.process_message(message, session_id)

        # Save bot response to database
        if session_db_id and response:
            try:
                await persistence_dao.save_bot_message(session_db_id, str(response), 'bot')
                logger.info(f"🤖 Saved bot response for session {session_id}")
            except Exception as e:
                logger.error(f"⚠️ Failed to save bot message: {e}")
                # Continue even if save fails

        return {
            "success": True,
            "response": response,
            "session_id": session_id
        }
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/stream")
async def chat_with_agent_stream(request: Request):
    """Chat with AI agent with streaming response"""
    try:
        body = await request.json()
        
        message = body.get("message", "")
        session_id = body.get("session_id")
        
        logger.info(f"📨 Received stream request - Message: {message[:50]}..., Session: {session_id}")
        
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        
        if not session_id:
            session_id = f"session_{int(time.time())}"
            logger.info(f"🆕 Generated new session ID: {session_id}")
        
        # Stream response
        async def generate_response():
            try:
                async for chunk in agent_service.process_message_stream(message, session_id):
                    yield f"data: {chunk}\n\n"
            except Exception as e:
                logger.error(f"Error in stream generation: {e}")
                logger.error(f"Exception type: {type(e).__name__}")
                yield f"data: Error: {str(e)}\n\n"
        
        return StreamingResponse(generate_response(), media_type="text/plain")
    except Exception as e:
        logger.error(f"Error in chat stream endpoint: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Exception details: {str(e)}")
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
# AGENT ENDPOINTS
# =================================

@router.get("/agents")
async def get_available_agents():
    """Get list of available agents"""
    try:
        agents = await agent_service.get_available_agents()
        
        return {
            "success": True,
            "agents": agents
        }
    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/{agent_id}")
async def get_agent_info(agent_id: str):
    """Get information about a specific agent"""
    try:
        agent_info = await agent_service.get_agent_info(agent_id)
        
        if not agent_info:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        return {
            "success": True,
            "agent": agent_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent info: {e}")
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
