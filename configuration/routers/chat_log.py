"""
Chat Log Endpoints for Human Agents
Handles chat session management, assignment, and messaging for human agents.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from configuration.core.logging_config import get_railway_logger

from ..service.chat_log_service import ChatLogService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["chat-log"])

# Public router for chat endpoints (no authentication required)
public_chat_router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class SendMessageRequest(BaseModel):
    text: str
    agent_id: str


class ArchiveSessionRequest(BaseModel):
    archive_status: str


@router.post("/agents/heartbeat")
async def agent_heartbeat(request: Request):
    """Heartbeat endpoint for agents."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        await service.update_agent_heartbeat(user_email)
        return {"success": True, "message": "Heartbeat received"}
    except Exception as e:
        logger.error(f"Error processing heartbeat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing heartbeat: {str(e)}")


@router.get("/chat-sessions")
async def get_chat_sessions(
    request: Request,
    agent_id: Optional[str] = Query(None),
    role: str = Query("human_agent"),
    archive_status: Optional[str] = Query("active", description="Filter by archive status: active, closed, archived, transferred"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(50, ge=1, le=200, description="Number of sessions per page")
):
    """
    Get chat sessions for human agents.
    """
    try:
        # Get user data from request state (set by middleware)
        user_data = request.state.user
        
        service = ChatLogService()
        result = await service.get_chat_sessions(
            agent_id=agent_id,
            role=role,
            archive_status=archive_status,
            page=page,
            limit=limit
        )
        return result
    except Exception as e:
        logger.error(f"Error fetching chat sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching chat sessions: {str(e)}")


@router.put("/chat-sessions/{session_id}/archive")
async def archive_chat_session(
    session_id: str,
    request: ArchiveSessionRequest,
    request_obj: Request
):
    """Archive or change status of a chat session."""
    # Get user email from headers (set by API Gateway)
    user_email = request_obj.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.archive_chat_session(
            session_id=session_id,
            archive_status=request.archive_status,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error archiving chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error archiving chat session: {str(e)}")


@router.get("/chat-sessions/{session_id}/messages", response_model=dict)
async def get_session_messages(
    session_id: str,
    request: Request
):
    """Get all messages for a specific chat session."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.get_session_messages(session_id, user_email)
        return result
    except Exception as e:
        logger.error(f"Error fetching session messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching session messages: {str(e)}")


@router.post("/chat-sessions/{session_id}/messages")
async def send_agent_message(
    session_id: str,
    request: SendMessageRequest,
    request_obj: Request
):
    """Send a message from an agent to a customer."""
    # Get user email from headers (set by API Gateway)
    user_email = request_obj.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.send_agent_message(
            session_id=session_id,
            text=request.text,
            agent_id=request.agent_id,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error sending agent message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error sending agent message: {str(e)}")


@router.get("/chat-sessions/{session_id}/events")
async def agent_chat_sse(session_id: str, request: Request):
    """SSE endpoint for agent chat events."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        return await service.get_chat_events_stream(session_id, user_email)
    except Exception as e:
        logger.error(f"Error in SSE stream: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error in SSE stream: {str(e)}")


@router.post("/chat-sessions/assign")
async def assign_chat_session(
    request: Request,
    session_id: str = Query(..., description="Customer chat session ID")
):
    """Assign a chat session to an available agent using load balancing."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.assign_chat_session(session_id, user_email)
        return result
    except Exception as e:
        logger.error(f"Error assigning chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error assigning chat session: {str(e)}")


@router.post("/chat-sessions/{session_id}/transfer")
async def transfer_chat_session(
    request: Request,
    session_id: str,
    target_agent_email: str = Query(..., description="Email of the agent or admin to transfer to")
):
    """Transfer a chat session to another agent or admin."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.transfer_chat_session(
            session_id=session_id,
            target_agent_email=target_agent_email,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error transferring chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error transferring chat session: {str(e)}")


@router.put("/chat-sessions/{session_id}/update")
async def update_chat_session(
    request: Request,
    session_id: str,
    assigned_agent: Optional[str] = Query(None, description="Assigned agent email"),
    feedback: Optional[str] = Query(None, description="Session feedback: 'positive' or 'negative'"),
    user_type: Optional[str] = Query(None, description="User type providing feedback: 'customer' or 'agent'")
):
    """Update a chat session."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.update_chat_session(
            session_id=session_id,
            assigned_agent=assigned_agent,
            feedback=feedback,
            user_type=user_type,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error updating chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating chat session: {str(e)}")


@router.post("/chat-sessions/{session_id}/end-agent", response_model=dict)
async def end_agent_session(
    request: Request,
    session_id: str
):
    """End agent session."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.end_agent_session(session_id, user_email)
        return result
    except Exception as e:
        logger.error(f"Error ending agent session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error ending agent session: {str(e)}")


@router.put("/chat-sessions/{session_id}/feedback", response_model=dict)
async def update_chat_session_feedback(
    request: Request,
    session_id: str,
    feedback: str = Query(..., description="Session feedback: 'positive' or 'negative'"),
    user_type: str = Query("customer", description="User type providing feedback: 'customer' or 'agent'")
):
    """Update chat session feedback."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.update_session_feedback(
            session_id=session_id,
            feedback=feedback,
            user_type=user_type,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error updating session feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating session feedback: {str(e)}")


# Public chat endpoints (no authentication required)
@public_chat_router.post("/{session_id}/request-agent")
async def request_human_agent(session_id: str):
    """Request human agent assistance for a chat session."""
    try:
        service = ChatLogService()
        result = await service.request_human_agent(session_id)
        return result
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")


# Admin chat session request-agent endpoint (authenticated)
@router.post("/chat-sessions/{session_id}/request-agent", response_model=dict)
async def admin_request_human_agent(
    request: Request,
    session_id: str
):
    """Request human agent assistance for a chat session (admin endpoint)."""
    # Get user email from headers (set by API Gateway)
    user_email = request.headers.get("X-User-Email", "")
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = ChatLogService()
        result = await service.request_human_agent(session_id)
        return result
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")
