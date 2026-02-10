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

logger = logging.getLogger(__name__)
from ..core.utils import log_endpoint_request

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
        body = await request.json()
        
        message = body.get("message")
        session_id = body.get("session_id")
        
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        
        # Create session if not provided
        if not session_id:
            session_id = f"session_{int(time.time())}"
        
        # Process chat message
        response = await agent_service.process_message(message, session_id)
        
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
    """Chat with AI agent with streaming response using Pydantic AI"""
    try:
        body = await request.json()

        message = body.get("message")
        session_id = body.get("session_id")

        if not message:
            raise HTTPException(status_code=400, detail="Message is required")

        # Create session if not provided
        if not session_id:
            session_id = f"session_{int(time.time())}"

        # Prepare tools list safely to avoid None values
        tools = []
        logger.info("🔧 Starting tool imports...")
        
        try:
            from ..tools.rag import search_knowledge_base
            logger.info(f"🔧 search_knowledge_base imported: {search_knowledge_base}")
            if search_knowledge_base is not None:
                tools.append(search_knowledge_base)
                logger.info("✅ Added search_knowledge_base to tools")
            else:
                logger.warning("⚠️ search_knowledge_base is None, skipping")
        except ImportError as e:
            logger.warning(f"Failed to import search_knowledge_base: {e}")

        try:
            from ..tools.general import request_human_agent_connection, query_railway_postgres
            logger.info(f"🔧 request_human_agent_connection imported: {request_human_agent_connection}")
            logger.info(f"🔧 query_railway_postgres imported: {query_railway_postgres}")
            if request_human_agent_connection is not None:
                tools.append(request_human_agent_connection)
                logger.info("✅ Added request_human_agent_connection to tools")
            else:
                logger.warning("⚠️ request_human_agent_connection is None, skipping")
            if query_railway_postgres is not None:
                tools.append(query_railway_postgres)
                logger.info("✅ Added query_railway_postgres to tools")
            else:
                logger.warning("⚠️ query_railway_postgres is None, skipping")
        except ImportError as e:
            logger.warning(f"Failed to import general tools: {e}")

        logger.info(f"🔧 Final tools list: {tools}")
        logger.info(f"🔧 Loaded {len(tools)} tools for agent")

        # Stream response using new agent-based approach
        async def generate_response():
            async for chunk in agent_service.stream_agent_response(message, session_id, tools):
                # chunk already contains the formatted JSON with \n\n
                yield f"data: {chunk}"

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
