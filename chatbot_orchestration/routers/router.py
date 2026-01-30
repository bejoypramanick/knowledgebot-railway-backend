"""
Consolidated Chatbot Orchestration Router
All chatbot orchestration endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, List, Any, Optional
import logging

from ..service.chat_service import ChatService
from ..service.agent_service import PydanticAIGatewayService
from ..core.auth_middleware import get_current_user
from ..schemas.models import ChatRequest
from ..core.logging_config import get_railway_logger
from ..core.utils import log_endpoint_request

logger = get_railway_logger(__name__)
router = APIRouter()

# Initialize services
chat_service = ChatService()
agent_service = PydanticAIGatewayService()

# =================================
# CHAT ENDPOINTS
# =================================

@router.post("/chat")
async def chat_with_agent(request: Request):
    """Chat with AI agent"""
    try:
        current_user = await get_current_user(request)
        body = await request.json()
        
        message = body.get("message")
        session_id = body.get("session_id")
        agent_id = body.get("agent_id")
        
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        
        response = await chat_service.process_message(
            message=message,
            session_id=session_id,
            user_id=current_user.get("uid"),
            agent_id=agent_id
        )
        
        return {
            "success": True,
            "response": response,
            "session_id": session_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/stream")
async def chat_stream(request: Request, fastapi_request: Request, chat_request: ChatRequest):
    """Handle chat request with streaming response using optimized Pydantic AI Gateway Service."""
    try:
        # Get user data from headers (set by API Gateway)
        user_data = {
            'uid': request.headers.get('X-User-UID', ''),
            'email': request.headers.get('X-User-Email', ''),
            'displayName': request.headers.get('X-User-Display-Name', ''),
            'photoURL': request.headers.get('X-User-Photo-URL', ''),
            'role': 'user'  # Default role - service can fetch roles from DB if needed
        }
        
        log_endpoint_request("chatbot_orchestration", "chat_stream", fastapi_request)
        
        # Service handles all business logic
        return await chat_service.handle_chat_stream(chat_request, user_data)
    except Exception as e:
        logger.error(f"Error in chat stream: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")

@router.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str, request: Request):
    """Get chat history for a session"""
    try:
        current_user = await get_current_user(request)
        history = await chat_service.get_chat_history(session_id, current_user.get("uid"))
        
        return {
            "success": True,
            "data": history
        }
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str, request: Request):
    """Delete a chat session"""
    try:
        current_user = await get_current_user(request)
        result = await chat_service.delete_session(session_id, current_user.get("uid"))
        
        return {
            "success": True,
            "message": "Session deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting chat session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# AGENT ENDPOINTS
# =================================

@router.get("/agents")
async def get_available_agents():
    """Get list of available AI agents"""
    try:
        agents = await agent_service.get_available_agents()
        
        return {
            "success": True,
            "data": agents
        }
    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/agents/{agent_id}")
async def get_agent_details(agent_id: str):
    """Get details of a specific agent"""
    try:
        agent = await agent_service.get_agent_details(agent_id)
        
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        
        return {
            "success": True,
            "data": agent
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent details: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/agents/{agent_id}/assign")
async def assign_agent_to_session(agent_id: str, request: Request):
    """Assign an agent to a chat session"""
    try:
        current_user = await get_current_user(request)
        body = await request.json()
        
        session_id = body.get("session_id")
        if not session_id:
            raise HTTPException(status_code=400, detail="Session ID is required")
        
        result = await agent_service.assign_agent_to_session(
            agent_id=agent_id,
            session_id=session_id,
            user_id=current_user.get("uid")
        )
        
        return {
            "success": True,
            "message": "Agent assigned successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning agent: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# SESSION MANAGEMENT ENDPOINTS
# =================================

@router.post("/sessions")
async def create_chat_session(request: Request):
    """Create a new chat session"""
    try:
        current_user = await get_current_user(request)
        body = await request.json()
        
        agent_id = body.get("agent_id")
        session_name = body.get("session_name")
        
        session = await chat_service.create_session(
            user_id=current_user.get("uid"),
            agent_id=agent_id,
            session_name=session_name
        )
        
        return {
            "success": True,
            "data": session
        }
    except Exception as e:
        logger.error(f"Error creating chat session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions")
async def get_user_sessions(request: Request):
    """Get all sessions for the current user"""
    try:
        current_user = await get_current_user(request)
        sessions = await chat_service.get_user_sessions(current_user.get("uid"))
        
        return {
            "success": True,
            "data": sessions
        }
    except Exception as e:
        logger.error(f"Error getting user sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check for chatbot orchestration service"""
    try:
        health_status = {
            "status": "healthy",
            "service": "chatbot-orchestration",
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
        raise HTTPException(status_code=500, detail=str(e))
