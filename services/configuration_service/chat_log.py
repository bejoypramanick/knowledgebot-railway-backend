"""
Chat Log Endpoints for Human Agents
Handles chat session management, assignment, and messaging for human agents.
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel
from typing import List, Optional
import logging
import sys
from pathlib import Path
from datetime import datetime
import uuid
import json
import os

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["chat-log"])

# Public router for chat endpoints (no authentication required)
public_chat_router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatMessageResponse(BaseModel):
    id: str
    text: str
    sender: str  # 'user', 'agent', 'bot'
    timestamp: str
    session_id: str


class ChatSessionResponse(BaseModel):
    id: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    status: str  # 'active', 'waiting', 'closed'
    last_message_at: str
    assigned_agent: Optional[str] = None
    messages: List[ChatMessageResponse] = []


class ChatSessionsResponse(BaseModel):
    sessions: List[ChatSessionResponse]


class SendMessageRequest(BaseModel):
    text: str
    sender: str = 'agent'
    agent_id: str


class SendMessageResponse(BaseModel):
    message_id: str
    success: bool


async def get_agent_online_status(agent_email: str, conn) -> bool:
    """
    Check if an agent is online by checking their last activity timestamp.
    An agent is considered online if they've accessed the chat log within the last 10 minutes.
    """
    try:
        # Check if agent has accessed chat log recently (within last 10 minutes)
        # We track this via the chat_sessions endpoint being called by the agent
        # For now, we'll check if the agent has any recent activity in their assigned chats
        # or if they've accessed the chat log endpoint recently
        
        # Check for recent activity: agent has accessed chat log or has active chats
        # An agent with active chats is likely online
        recent_activity = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM human_agent_sessions 
            WHERE agent_email = $1 
            AND status IN ('waiting', 'connected')
            AND connected_at > NOW() - INTERVAL '10 minutes'
            """,
            agent_email
        ) or 0
        
        # Also check if agent has accessed their chat log recently
        # We can infer this from recent chat_sessions queries or last_activity_at
        # For now, if they have any active chats, consider them online
        if recent_activity > 0:
            return True
        
        # Check if agent has been assigned any chats recently (within last 30 minutes)
        # This indicates they might be active
        recent_assignment = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM human_agent_sessions 
            WHERE agent_email = $1 
            AND connected_at > NOW() - INTERVAL '30 minutes'
            """,
            agent_email
        ) or 0
        
        # If agent has recent assignments, they're likely online
        return recent_assignment > 0
        
    except Exception as e:
        logger.error(f"Error checking agent online status for {agent_email}: {e}")
        # Default to True to avoid blocking chat assignments if there's an error
        return True


async def assign_chat_to_agent(session_id: str, agent_email: str, conn) -> None:
    """Assign a chat session to a human agent and send notification."""
    try:
        # Update chat_sessions table to assign agent
        # First, get the chat_sessions id from session_id
        session_row = await conn.fetchrow(
            "SELECT id FROM chat_sessions WHERE session_id = $1",
            session_id
        )
        
        if not session_row:
            # Create a new session if it doesn't exist
            session_db_id = await conn.fetchval(
                """
                INSERT INTO chat_sessions (session_id, is_active, metadata)
                VALUES ($1, TRUE, $2::jsonb)
                RETURNING id
                """,
                session_id,
                {"assigned_agent": agent_email, "status": "active"}
            )
        else:
            session_db_id = session_row['id']
            # Update existing session
            await conn.execute(
                """
                UPDATE chat_sessions 
                SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $2
                """,
                {"assigned_agent": agent_email, "status": "active"},
                session_db_id
            )
        
        # Create or update human_agent_sessions entry
        existing = await conn.fetchrow(
            """
            SELECT id FROM human_agent_sessions 
            WHERE customer_session_id = $1
            """,
            session_id
        )
        
        if existing:
            await conn.execute(
                """
                UPDATE human_agent_sessions
                SET agent_email = $1, status = 'waiting', connected_at = CURRENT_TIMESTAMP
                WHERE customer_session_id = $2
                """,
                agent_email, session_id
            )
        else:
            await conn.execute(
                """
                INSERT INTO human_agent_sessions (customer_session_id, agent_email, status, connected_at)
                VALUES ($1, $2, 'waiting', CURRENT_TIMESTAMP)
                """,
                session_id, agent_email
            )
        
        logger.info(f"Chat session {session_id} assigned to agent {agent_email} - will appear in chat log")
        
    except Exception as e:
        logger.error(f"Error assigning chat to agent: {e}", exc_info=True)
        raise


async def get_agent_chat_count(agent_email: str, conn) -> int:
    """Get the number of active chats assigned to an agent."""
    try:
        # Count from both human_agent_sessions and chat_sessions metadata
        # This ensures we count all active chats regardless of where they're stored
        count1 = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM human_agent_sessions 
            WHERE agent_email = $1 AND status IN ('waiting', 'connected')
            """,
            agent_email
        ) or 0
        
        # Also count from chat_sessions where agent is assigned in metadata
        count2 = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM chat_sessions 
            WHERE is_active = TRUE 
            AND (metadata->>'assigned_agent') = $1
            AND (metadata->>'status') IN ('active', 'waiting', 'connected')
            """,
            agent_email
        ) or 0
        
        # Return the maximum count (to avoid double counting if both exist)
        # In practice, both should be in sync, but we take max to be safe
        return max(count1, count2)
    except Exception as e:
        logger.error(f"Error getting agent chat count: {e}")
        return 0


async def assign_chat_with_load_balancing(session_id: str, conn) -> Optional[str]:
    """
    Assign a chat to an available agent using round-robin load balancing.
    Returns the assigned agent email or None if no agents available.
    """
    try:
        # Get all confirmed human agents
        agents = await conn.fetch(
            """
            SELECT email FROM human_agents 
            WHERE status = 'confirmed'
            ORDER BY email
            """
        )
        
        if not agents:
            logger.warning("No confirmed human agents available")
            return None
        
        # Get chat counts for each ONLINE agent only
        agent_loads = []
        for agent in agents:
            agent_email = agent['email']
            # Check if agent is online (has recent activity)
            is_online = await get_agent_online_status(agent_email, conn)
            if is_online:
                chat_count = await get_agent_chat_count(agent_email, conn)
                agent_loads.append({
                    'email': agent_email,
                    'chat_count': chat_count
                })
                logger.debug(f"Agent {agent_email} is online with {chat_count} active chats")
            else:
                logger.debug(f"Agent {agent_email} is offline (no recent activity)")
        
        if not agent_loads:
            logger.warning("No online agents available")
            return None
        
        # Sort by chat count (load balancing - assign to agent with fewest chats)
        agent_loads.sort(key=lambda x: x['chat_count'])
        
        # Assign to agent with lowest load
        assigned_agent = agent_loads[0]['email']
        await assign_chat_to_agent(session_id, assigned_agent, conn)
        
        logger.info(f"Assigned chat {session_id} to agent {assigned_agent} (load: {agent_loads[0]['chat_count']})")
        return assigned_agent
        
    except Exception as e:
        logger.error(f"Error in load balancing: {e}", exc_info=True)
        return None


@router.post("/agents/heartbeat")
async def agent_heartbeat(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """
    Heartbeat endpoint for agents to indicate they're online and active.
    This helps track which agents are currently logged in and available.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=401, detail="User email not found")
        
        # Check if user is a human agent
        conn = await railway_db.get_connection()
        try:
            agent = await conn.fetchrow(
                """
                SELECT email FROM human_agents 
                WHERE email = $1 AND status = 'confirmed'
                """,
                user_email
            )
            
            if not agent:
                raise HTTPException(status_code=403, detail="User is not a confirmed human agent")
            
            # Update last activity timestamp for this agent
            # We'll use the human_agent_sessions table to track activity
            # by updating the most recent session's connected_at timestamp
            # or we can create a separate tracking mechanism
            
            # For now, we'll update any recent session to indicate activity
            await conn.execute(
                """
                UPDATE human_agent_sessions 
                SET connected_at = CURRENT_TIMESTAMP
                WHERE agent_email = $1 
                AND connected_at > NOW() - INTERVAL '1 hour'
                LIMIT 1
                """,
                user_email
            )
            
            logger.debug(f"Heartbeat received from agent {user_email}")
            
            return {
                "success": True,
                "message": "Heartbeat recorded",
                "agent_email": user_email
            }
        finally:
            await conn.close()
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing agent heartbeat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing heartbeat: {str(e)}")


@router.get("/chat-sessions", response_model=ChatSessionsResponse)
async def get_assigned_chat_sessions(
    request: Request,
    role: Optional[str] = Query(None, description="User role: admin, human_agent, or user"),
    agent_id: Optional[str] = Query(None, description="Agent email or ID (optional for admins/users)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get chat sessions:
    - For human agents: only their assigned sessions
    - For admins/users: all sessions
    """
    # Debug: Log all query parameters
    logger.info(f"Request URL: {request.url}")
    logger.info(f"Query params: {dict(request.query_params)}")
    logger.info(f"Role from Query: {role}")
    
    # If role is not provided in Query, try to get it from request query params
    if not role:
        role = request.query_params.get("role")
        logger.info(f"Role from request.query_params: {role}")
    
    if not role:
        logger.error(f"Role parameter missing. All query params: {dict(request.query_params)}")
        raise HTTPException(status_code=422, detail="Role query parameter is required")
    
    # Validate role value
    if role not in ['admin', 'human_agent', 'user']:
        raise HTTPException(status_code=422, detail=f"Invalid role: {role}. Must be one of: admin, human_agent, user")
    
    logger.info(f"Using role: {role}, agent_id: {agent_id}")
    
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        # For human agents, only return their own sessions
        # Use the authenticated user's email to ensure they can only see their own chats
        if role == 'human_agent':
            # Always use the authenticated user's email for filtering (security)
            # Ignore agent_id parameter to prevent viewing other agents' chats
            agent_id = user_email
            logger.info(f"Human agent {user_email} requesting their assigned chats")
        # For admins and regular users, show all sessions
        elif role in ['admin', 'user']:
            agent_id = None  # Don't filter by agent for admins/users
        
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # Build query based on role
            if role == 'human_agent' and agent_id:
                # Human agents: only their assigned sessions
                # Filter by agent_email in human_agent_sessions table to ensure they only see their chats
                sessions_data = await conn.fetch(
                    """
                    SELECT DISTINCT
                        cs.id,
                        cs.session_id,
                        cs.last_activity_at,
                        cs.metadata,
                        cs.is_active
                    FROM chat_sessions cs
                    INNER JOIN human_agent_sessions has ON cs.session_id = has.customer_session_id
                    WHERE LOWER(has.agent_email) = LOWER($1)
                    AND has.status IN ('waiting', 'connected')
                    ORDER BY cs.last_activity_at DESC
                    """,
                    agent_id
                )
                logger.info(f"Found {len(sessions_data)} sessions for human agent {agent_id}")
            else:
                # Admins and users: all sessions
                sessions_data = await conn.fetch(
                    """
                    SELECT DISTINCT
                        cs.id,
                        cs.session_id,
                        cs.last_activity_at,
                        cs.metadata,
                        cs.is_active,
                        has.agent_email
                    FROM chat_sessions cs
                    LEFT JOIN human_agent_sessions has ON cs.session_id = has.customer_session_id
                    ORDER BY cs.last_activity_at DESC
                    """
                )
            
            sessions = []
            for session_row in sessions_data:
                session_id = session_row['session_id']
                # Parse metadata - it might be a JSON string or already a dict
                raw_metadata = session_row['metadata']
                if raw_metadata is None:
                    metadata = {}
                elif isinstance(raw_metadata, str):
                    try:
                        metadata = json.loads(raw_metadata)
                    except (json.JSONDecodeError, TypeError):
                        metadata = {}
                elif isinstance(raw_metadata, dict):
                    metadata = raw_metadata
                else:
                    metadata = {}
                
                # Get messages for this session
                session_db_id = session_row['id']
                messages_data = await conn.fetch(
                    """
                    SELECT 
                        id::text,
                        role,
                        content,
                        created_at
                    FROM chat_messages
                    WHERE session_id = $1
                    ORDER BY created_at ASC
                    """,
                    session_db_id
                )
                
                messages = []
                for msg in messages_data:
                    # Map role to sender: 'user' -> 'user', 'assistant' -> 'bot', 'agent' -> 'agent'
                    sender = 'bot' if msg['role'] == 'assistant' else msg['role']
                    messages.append(ChatMessageResponse(
                        id=str(msg['id']),
                        text=msg['content'],
                        sender=sender,
                        timestamp=msg['created_at'].isoformat() if msg['created_at'] else datetime.now().isoformat(),
                        session_id=session_id
                    ))
                
                # Determine status
                status = 'active' if session_row['is_active'] else 'closed'
                if metadata.get('status'):
                    status = metadata['status']
                
                # Get assigned agent from session_row if available (for admin/user queries)
                assigned_agent = metadata.get('assigned_agent')
                if not assigned_agent and 'agent_email' in session_row and session_row['agent_email']:
                    assigned_agent = session_row['agent_email']
                if not assigned_agent and agent_id:
                    assigned_agent = agent_id
                
                sessions.append(ChatSessionResponse(
                    id=session_id,
                    customer_name=metadata.get('customer_name'),
                    customer_email=metadata.get('customer_email'),
                    status=status,
                    last_message_at=session_row['last_activity_at'].isoformat() if session_row['last_activity_at'] else datetime.now().isoformat(),
                    assigned_agent=assigned_agent,
                    messages=messages
                ))
            
            return ChatSessionsResponse(sessions=sessions)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching assigned chat sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching chat sessions: {str(e)}")


@router.get("/chat-sessions/{session_id}/messages", response_model=dict)
async def get_session_messages(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get all messages for a specific chat session.
    Accessible by all authenticated users.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # All authenticated users can view messages
            
            # Get session database ID
            session_row = await conn.fetchrow(
                "SELECT id FROM chat_sessions WHERE session_id = $1",
                session_id
            )
            
            if not session_row:
                return {"messages": []}
            
            session_db_id = session_row['id']
            
            # Get messages
            messages_data = await conn.fetch(
                """
                SELECT 
                    id::text,
                    role,
                    content,
                    created_at
                FROM chat_messages
                WHERE session_id = $1
                ORDER BY created_at ASC
                """,
                session_db_id
            )
            
            messages = []
            for msg in messages_data:
                sender = 'bot' if msg['role'] == 'assistant' else msg['role']
                messages.append({
                    "id": str(msg['id']),
                    "text": msg['content'],
                    "sender": sender,
                    "timestamp": msg['created_at'].isoformat() if msg['created_at'] else datetime.now().isoformat(),
                    "session_id": session_id
                })
            
            return {"messages": messages}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching session messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching messages: {str(e)}")


@router.post("/chat-sessions/{session_id}/messages", response_model=SendMessageResponse)
async def send_agent_message(
    session_id: str,
    request: SendMessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Send a message from a user/agent to a customer.
    All authenticated users can send messages.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        # Verify agent_id matches current user
        if request.agent_id != user_email:
            raise HTTPException(status_code=403, detail="Agent ID must match authenticated user")
        
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # All authenticated users can send messages to any session
            
            # Get session database ID
            session_row = await conn.fetchrow(
                "SELECT id FROM chat_sessions WHERE session_id = $1",
                session_id
            )
            
            if not session_row:
                raise HTTPException(status_code=404, detail="Chat session not found")
            
            session_db_id = session_row['id']
            
            # Insert message
            message_id = await conn.fetchval(
                """
                INSERT INTO chat_messages (session_id, role, content)
                VALUES ($1, 'agent', $2)
                RETURNING id::text
                """,
                session_db_id,
                request.text
            )
            
            # Update session last activity
            await conn.execute(
                """
                UPDATE chat_sessions 
                SET last_activity_at = CURRENT_TIMESTAMP,
                    message_count = message_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                session_db_id
            )
            
            logger.info(f"Agent {user_email} sent message to session {session_id}")
            
            return SendMessageResponse(
                message_id=message_id,
                success=True
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending agent message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error sending message: {str(e)}")


@router.post("/chat-sessions/assign", response_model=dict)
async def assign_chat_session(
    session_id: str = Query(..., description="Customer chat session ID"),
    current_user: dict = Depends(get_current_user)
):
    """
    Assign a chat session to an available agent using load balancing.
    This endpoint is called when a customer requests to connect to a human agent.
    Only admins can manually assign, otherwise it's automatic.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # Check if user is admin (for manual assignment)
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            
            # Use load balancing to assign chat
            assigned_agent = await assign_chat_with_load_balancing(session_id, conn)
            
            if not assigned_agent:
                raise HTTPException(status_code=503, detail="No available agents to assign chat")
            
            return {
                "success": True,
                "message": f"Chat assigned to agent {assigned_agent}",
                "assigned_agent": assigned_agent,
                "session_id": session_id
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error assigning chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error assigning chat: {str(e)}")


@public_chat_router.post("/{session_id}/request-human-agent", response_model=dict)
async def request_human_agent(
    session_id: str,
    request: Request
):
    """
    Request human agent connection for a chat session.
    This endpoint is called from the chatbot widget when a customer requests to connect to a human agent.
    It performs load balancing to assign the chat to the agent with the least number of active chats.
    No authentication required - called from public chatbot widget.
    """
    try:
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # Check if HIL is enabled (default to true if not set)
            config = await conn.fetchrow(
                "SELECT hil_enabled FROM chatbot_configuration WHERE admin_user = 'GLOBISTAAN' LIMIT 1"
            )
            
            # Default to enabled if not set (hil_enabled can be NULL, which means enabled by default)
            hil_enabled = config.get('hil_enabled') if config and config.get('hil_enabled') is not None else True
            
            if not hil_enabled:
                raise HTTPException(
                    status_code=503, 
                    detail="Human agent support is currently disabled"
                )
            
            # Use load balancing to assign chat to agent with least active chats
            assigned_agent = await assign_chat_with_load_balancing(session_id, conn)
            
            if not assigned_agent:
                raise HTTPException(
                    status_code=503, 
                    detail="No available agents to assign chat. Please try again later."
                )
            
            logger.info(f"Chat session {session_id} assigned to agent {assigned_agent} via request-human-agent endpoint")
            
            return {
                "success": True,
                "message": f"Chat assigned to agent {assigned_agent}",
                "assigned_agent": assigned_agent,
                "session_id": session_id
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")

