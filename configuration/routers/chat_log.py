"""
Chat Log Endpoints for Human Agents
Handles chat session management, assignment, and messaging for human agents.
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Set
from shared.logging_config import get_railway_logger
import logging
from datetime import datetime, timedelta
import uuid
import json
import time
import os
import asyncio

from shared.auth_middleware import get_current_user

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["chat-log"])

# Public router for chat endpoints (no authentication required)
public_chat_router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


from .schemas.chat_log_schemas import (
    ChatMessageResponse, ChatSessionResponse, ChatSessionsResponse,
    SendMessageRequest, SendMessageResponse
)
from .service.chat_log_service import ChatLogService
from .utils.sse_manager import connection_manager


@router.get("/agents/online", response_model=dict)
async def get_online_agents(current_user: dict = Depends(get_current_user)):
    """Get all online human agents and admins."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")

    service = ChatLogService(connection_manager)  # Service manages its own DAO
    agents = await service.get_online_agents(user_email)
    return {"success": True, "agents": agents}


@router.post("/agents/heartbeat")
async def agent_heartbeat(current_user: dict = Depends(get_current_user)):
    """Heartbeat endpoint for agents."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=401, detail="User email not found")
    
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    await service.record_heartbeat(user_email)
    return {"success": True, "message": "Heartbeat recorded", "agent_email": user_email}


@router.get("/chat-sessions", response_model=ChatSessionsResponse)
async def get_assigned_chat_sessions(
    request: Request,
    role: Optional[str] = Query(None, description="User role: admin, human_agent, or user"),
    agent_id: Optional[str] = Query(None, description="Agent email or ID (optional for admins/users)"),
    archive_status: Optional[str] = Query("active", description="Filter by archive status: active, closed, archived, transferred"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(50, ge=1, le=200, description="Number of sessions per page"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get chat sessions.
    """
    if not role:
        role = request.query_params.get("role")
    
    if not role:
        raise HTTPException(status_code=422, detail="Role query parameter is required")
    
    if role not in ['admin', 'human_agent', 'user']:
        raise HTTPException(status_code=422, detail=f"Invalid role: {role}")

    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")
    
    try:
        service = ChatLogService(connection_manager)  # Service manages its own DAO
        
        sessions, total_count = await service.get_chat_sessions(
            role=role,
            user_email=user_email,
            archive_status=archive_status,
            page=page,
            limit=limit,
            agent_id=agent_id
        )
        
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1
        return ChatSessionsResponse(
            sessions=sessions,
            total_count=total_count,
            page=page,
            limit=limit,
            total_pages=total_pages
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching assigned chat sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching chat sessions: {str(e)}")


class ArchiveSessionRequest(BaseModel):
    status: str

@router.put("/chat-sessions/{session_id}/archive", response_model=dict)
async def archive_chat_session(
    session_id: str,
    request: ArchiveSessionRequest,
    current_user: dict = Depends(get_current_user)
):
    """Archive or change status of a chat session."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")

    service = ChatLogService(connection_manager)  # Service manages its own DAO
    # Service handles role check internally
    await service.archive_chat_session(session_id, request.status, user_email)
    
    logger.info(f"Session {session_id} marked as {request.status} by {user_email}")
    return {
        "success": True,
        "message": f"Session status changed to {request.status}",
        "session_id": session_id,
        "status": request.status
    }


@router.get("/chat-sessions/{session_id}/messages", response_model=dict)
async def get_session_messages(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get all messages for a specific chat session."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")
    
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    messages_data = await service.get_session_messages(session_id)
    
    messages = [{
        "id": str(msg['id']),
        "text": msg['content'],
        "sender": msg['role'],
        "timestamp": msg['created_at'].isoformat() if msg['created_at'] else datetime.utcnow().isoformat(),
        "session_id": session_id
    } for msg in messages_data]
    
    return {"messages": messages}


@router.post("/chat-sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_agent_message(
    session_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """Send a message from an agent to a customer."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")
    
    if request.agent_id != user_email:
        raise HTTPException(status_code=403, detail="Agent ID must match authenticated user")
    
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    message_id = await service.send_agent_message(session_id, user_email, request.text)
    
    return SendMessageResponse(
        message_id=str(message_id),
        success=True
    )


@router.get("/chat-sessions/{session_id}/events")
async def agent_chat_sse(session_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """SSE endpoint for agent chat events."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    queue = await connection_manager.connect(response=None, session_id=session_id, user_type='agent')
    
    async def sse_generator():
        try:
            while True:
                try:
                    message = await connection_manager.get_next_message(queue)
                    if message:
                        yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except Exception as e:
            logger.error(f"Error in agent SSE generator: {e}")
        finally:
            await connection_manager.disconnect(queue)
    
    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )


@router.post("/chat-sessions/assign", response_model=dict)
async def assign_chat_session(
    session_id: str = Query(..., description="Customer chat session ID"),
    current_user: dict = Depends(get_current_user)
):
    """Assign a chat session to an available agent using load balancing."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")
    
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    
    assigned_agent = await service.assign_chat_with_load_balancing(session_id)
    
    if not assigned_agent:
        raise HTTPException(status_code=503, detail="No available agents to assign chat")
    
    return {
        "success": True,
        "message": f"Chat assigned to agent {assigned_agent}",
        "assigned_agent": assigned_agent,
        "session_id": session_id
    }


@router.post("/chat-sessions/{session_id}/transfer", response_model=dict)
async def transfer_chat_session(
    session_id: str,
    target_agent_email: str = Query(..., description="Email of the agent or admin to transfer to"),
    current_user: dict = Depends(get_current_user)
):
    """Transfer a chat session to another agent or admin."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")
        
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    await service.transfer_chat_session(session_id, user_email, target_agent_email)
    
    return {
        "success": True,
        "message": f"Chat transferred to {target_agent_email}",
        "assigned_agent": target_agent_email
    }


@router.patch("/chat-sessions/{session_id}", response_model=dict)
async def update_chat_session(
    session_id: str,
    status: Optional[str] = Query(None, description="Session status: 'active', 'waiting', or 'closed'"),
    assigned_agent: Optional[str] = Query(None, description="Assigned agent email"),
    feedback: Optional[str] = Query(None, description="Session feedback: 'positive' or 'negative'"),
    user_type: Optional[str] = Query(None, description="User type providing feedback: 'customer' or 'agent'"),
    current_user: dict = Depends(get_current_user)
):
    """Update a chat session."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found")
    
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    await service.update_chat_session(session_id, user_email, status, assigned_agent, feedback, user_type)
    return {'success': True, 'message': 'Session updated successfully'}


@router.post("/chat-sessions/{session_id}/end-customer", response_model=dict)
async def end_customer_session(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """End a chat session from the customer side."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=400, detail="User email is required")

    service = ChatLogService(connection_manager)  # Service manages its own DAO
    await service.end_customer_session(session_id, user_email)
    return {'success': True, 'message': 'Session ended successfully'}


@public_chat_router.post("/{session_id}/request-human-agent", response_model=dict)
async def request_human_agent(session_id: str, request: Request):
    """Request human agent connection for a chat session."""
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    assigned_agent = await service.request_human_agent(session_id)
    
    return {
        "success": True,
        "message": f"Chat assigned to agent {assigned_agent}",
        "assigned_agent": assigned_agent,
        "session_id": session_id
    }


@public_chat_router.patch("/{session_id}/end", response_model=dict)
async def public_end_customer_session(session_id: str, request: Request):
    """End a chat session from the customer side (public)."""
    service = ChatLogService(connection_manager)  # Service manages its own DAO
    await service.public_end_customer_session(session_id)
    return {"success": True, "message": "Session ended successfully"}


@public_chat_router.get("/{session_id}/events")
async def sse_customer_chat(session_id: str, request: Request):
    """SSE endpoint for customers."""
    queue = await connection_manager.connect(response=None, session_id=session_id, user_type='customer')
    
    async def event_generator():
        try:
            while True:
                try:
                    message = await connection_manager.get_next_message(queue)
                    if message:
                        yield f"data: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'ping'})}\n\n"
        except Exception as e:
            logger.error(f"Error in customer SSE: {e}")
        finally:
            await connection_manager.disconnect(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )



