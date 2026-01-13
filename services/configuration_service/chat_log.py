"""
Chat Log Endpoints for Human Agents
Handles chat session management, assignment, and messaging for human agents.
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Set
import logging
import sys
from pathlib import Path
from datetime import datetime, timedelta
import uuid
import json
import time
import os
import asyncio

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["chat-log"])

# Public router for chat endpoints (no authentication required)
public_chat_router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# SSE Connection Manager
class SSEConnectionManager:
    """Manages SSE connections for real-time chat between agents and customers."""

    def __init__(self):
        # Map session_id -> Set of SSE response objects
        # Each session can have multiple connections (agent + customer)
        self.active_connections: Dict[str, Set[object]] = {}
        # Map SSE response -> session_id for quick lookup
        self.connection_sessions: Dict[object, str] = {}
        # Map SSE response -> user_type ('agent' or 'customer')
        self.connection_types: Dict[object, str] = {}
        # Map SSE response -> queue for sending messages
        self.message_queues: Dict[object, asyncio.Queue] = {}
        self.lock = asyncio.Lock()

    async def connect(self, response, session_id: str, user_type: str = 'customer'):
        """Connect an SSE response to a session."""
        async with self.lock:
            if session_id not in self.active_connections:
                self.active_connections[session_id] = set()
            self.active_connections[session_id].add(response)
            self.connection_sessions[response] = session_id
            self.connection_types[response] = user_type
            self.message_queues[response] = asyncio.Queue()
        logger.info(f"SSE connected: {user_type} for session {session_id}")

    async def disconnect(self, response):
        """Disconnect an SSE response from a session."""
        async with self.lock:
            session_id = self.connection_sessions.pop(response, None)
            user_type = self.connection_types.pop(response, None)
            if session_id and session_id in self.active_connections:
                self.active_connections[session_id].discard(response)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
            # Clean up message queue
            if response in self.message_queues:
                del self.message_queues[response]
        logger.info(f"SSE disconnected: {user_type} from session {session_id}")

    async def send_personal_message(self, message: dict, response):
        """Send a message to a specific SSE connection."""
        try:
            if response in self.message_queues:
                await self.message_queues[response].put(message)
        except Exception as e:
            logger.error(f"Error queueing message for SSE: {e}")

    async def broadcast_to_session(self, message: dict, session_id: str, exclude_response=None):
        """Broadcast a message to all SSE connections in a session."""
        async with self.lock:
            connections = self.active_connections.get(session_id, set()).copy()

        if not connections:
            logger.warning(f"No active SSE connections for session {session_id}")
            return

        # Remove excluded connection if specified
        if exclude_response and exclude_response in connections:
            connections.remove(exclude_response)

        if not connections:
            logger.debug(f"No SSE connections to broadcast to after excluding sender")
            return

        # Queue messages to all connections
        send_tasks = []
        for connection in connections:
            send_tasks.append(self.send_personal_message(message, connection))

        # Wait for all queue operations to complete
        results = await asyncio.gather(*send_tasks, return_exceptions=True)
        success_count = sum(1 for r in results if not isinstance(r, Exception))

        logger.info(f"Queued message to {success_count}/{len(connections)} SSE connections for session {session_id}")

    async def get_next_message(self, response):
        """Get the next message for an SSE connection."""
        if response in self.message_queues:
            try:
                return await asyncio.wait_for(self.message_queues[response].get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                return {"type": "ping"}
        return None

    def get_session_connections(self, session_id: str):
        """Get all active connections for a session."""
        return self.active_connections.get(session_id, set()).copy()


# Global connection manager instance
connection_manager = SSEConnectionManager()


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
    created_at: Optional[str] = None
    assigned_agent: Optional[str] = None
    feedback: Optional[str] = None  # 'positive', 'negative', None (backward compatibility)
    customer_feedback: Optional[str] = None  # 'positive', 'negative', None
    agent_feedback: Optional[str] = None  # 'positive', 'negative', None
    sentiment: Optional[str] = None  # 'positive', 'negative', 'neutral', None
    chat_type: str  # 'human-handoff' if assigned_agent exists, 'ai-chat' otherwise
    messages: List[ChatMessageResponse] = []


class ChatSessionsResponse(BaseModel):
    sessions: List[ChatSessionResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int


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
    An agent is considered online if they've accessed the chat log within the last 30 minutes.
    We check for heartbeat entries (created when agent accesses chat log) and real chat sessions.
    """
    try:
        # Primary check: Look for heartbeat entry (created when agent accesses chat log)
        # This is the most reliable indicator that an agent is actively logged in
        heartbeat_session_id = f"heartbeat_{agent_email}"
        heartbeat_activity = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM session_assignments sa
            INNER JOIN chat_sessions cs ON sa.session_id = cs.id
            WHERE cs.session_id = $1
            AND sa.assigned_at > NOW() - INTERVAL '30 minutes'
            """,
            heartbeat_session_id
        ) or 0
        
        if heartbeat_activity > 0:
            logger.debug(f"Agent {agent_email} is online (heartbeat found)")
            return True
        
        # Secondary check: Look for any recent activity in assigned chats
        # This catches agents who have active chats but haven't accessed chat log recently
        recent_activity = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM session_assignments sa
            INNER JOIN chat_sessions cs ON sa.session_id = cs.id
            WHERE sa.assignee_email = $1 
            AND cs.session_id != $2
            AND sa.status IN ('waiting', 'active')
            AND sa.assigned_at > NOW() - INTERVAL '30 minutes'
            """,
            agent_email, heartbeat_session_id
        ) or 0
        
        if recent_activity > 0:
            logger.debug(f"Agent {agent_email} is online (recent chat activity found)")
            return True
        
        logger.debug(f"Agent {agent_email} is offline (no recent activity)")
        return False
        
    except Exception as e:
        logger.error(f"Error checking agent online status for {agent_email}: {e}")
        # Default to False to avoid assigning chats to offline agents
        # But log the error so we can debug
        return False


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
            metadata_dict = {"assigned_agent": agent_email, "status": "active"}
            session_db_id = await conn.fetchval(
                """
                INSERT INTO chat_sessions (session_id, is_active, metadata, last_activity_at, created_at)
                VALUES ($1, TRUE, $2::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id
                """,
                session_id,
                json.dumps(metadata_dict)
            )
        else:
            session_db_id = session_row['id']
            # Update existing session - ensure last_activity_at is set
            metadata_dict = {"assigned_agent": agent_email, "status": "active"}
            await conn.execute(
                """
                UPDATE chat_sessions 
                SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb,
                    last_activity_at = COALESCE(last_activity_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $2
                """,
                json.dumps(metadata_dict),
                session_db_id
            )
        
        # Determine assignee type (admin or agent)
        assignee_type = await conn.fetchval(
            """
            SELECT CASE 
                WHEN EXISTS (SELECT 1 FROM admins WHERE email = $1 AND status = 'confirmed') 
                THEN 'admin'
                ELSE 'agent'
            END
            """,
            agent_email
        )
        
        # Create or update session_assignments entry
        existing = await conn.fetchrow(
            """
            SELECT id FROM session_assignments 
            WHERE session_id = $1
            """,
            session_db_id
        )
        
        if existing:
            await conn.execute(
                """
                UPDATE session_assignments
                SET assignee_email = $1, assignee_type = $2, status = 'waiting', assigned_at = CURRENT_TIMESTAMP
                WHERE session_id = $3
                """,
                agent_email, assignee_type, session_db_id
            )
        else:
            await conn.execute(
                """
                INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status, assigned_at)
                VALUES ($1, $2, $3, 'waiting', CURRENT_TIMESTAMP)
                """,
                session_db_id, agent_email, assignee_type
            )
        
        # Ensure last_activity_at is updated so the session appears at the top of the list
        await conn.execute(
            """
            UPDATE chat_sessions 
            SET last_activity_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND (last_activity_at IS NULL OR last_activity_at < CURRENT_TIMESTAMP - INTERVAL '1 minute')
            """,
            session_db_id
        )
        
        logger.info(f"Chat session {session_id} assigned to agent {agent_email} - will appear in chat log")
        
    except Exception as e:
        logger.error(f"Error assigning chat to agent: {e}", exc_info=True)
        raise


async def get_agent_chat_count(agent_email: str, conn) -> int:
    """Get the number of active chats assigned to an agent."""
    try:
        # Count from session_assignments table
        count = await conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM session_assignments 
            WHERE assignee_email = $1 AND status IN ('waiting', 'active')
            """,
            agent_email
        ) or 0
        
        return count
    except Exception as e:
        logger.error(f"Error getting agent chat count: {e}")
        return 0


async def assign_chat_with_load_balancing(session_id: str, conn) -> Optional[str]:
    """
    Assign a chat to an available agent using round-robin load balancing.
    If no human agents are online, fallback to logged-in admins.
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
        
        agent_loads = []
        offline_agents = []
        
        if agents:
            logger.info(f"Found {len(agents)} confirmed human agent(s): {[a['email'] for a in agents]}")
            
            # Get chat counts for each ONLINE agent only
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
                    logger.info(f"Agent {agent_email} is online with {chat_count} active chats")
                else:
                    offline_agents.append(agent_email)
                    logger.info(f"Agent {agent_email} is offline (no recent activity in last 30 minutes)")
        
        if not agent_loads:
            if offline_agents:
                logger.warning(f"No online human agents available. All {len(offline_agents)} human agent(s) are offline. Falling back to admins.")
            else:
                logger.warning("No confirmed human agents available. Checking for admins.")
            
            # Fallback to admins
            admins = await conn.fetch(
                """
                SELECT email FROM admins 
                WHERE status = 'confirmed'
                ORDER BY email
                """
            )
            
            if not admins:
                logger.warning("No confirmed admins available in database")
                return None
                
            admin_loads = []
            offline_admins = []
            for admin in admins:
                admin_email = admin['email']
                is_online = await get_agent_online_status(admin_email, conn)
                if is_online:
                    chat_count = await get_agent_chat_count(admin_email, conn)
                    admin_loads.append({
                        'email': admin_email,
                        'chat_count': chat_count
                    })
                    logger.info(f"Admin {admin_email} is online with {chat_count} active chats")
                else:
                    offline_admins.append(admin_email)
            
            if not admin_loads:
                if offline_admins:
                    logger.warning(f"No online admins available. All {len(offline_admins)} admin(s) are offline.")
                else:
                    logger.warning("No confirmed admins available or online")
                return None
            
            # Use admin loads for assignment
            agent_loads = admin_loads
        
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


@router.get("/agents/online", response_model=dict)
async def get_online_agents(current_user: dict = Depends(get_current_user)):
    """
    Get all online human agents and admins with their active session counts.
    Used for load balancing and transfer UI.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")

        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Check if current user is an admin or agent
            is_agent = await conn.fetchval(
                "SELECT COUNT(*) FROM human_agents WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )

            if not is_agent and not is_admin:
                raise HTTPException(status_code=403, detail="Access denied")

            # Fetch all confirmed agents
            agents = await conn.fetch("SELECT email FROM human_agents WHERE status = 'confirmed'")
            # Fetch all confirmed admins
            admins = await conn.fetch("SELECT email FROM admins WHERE status = 'confirmed'")

            online_users = []

            # Check online status and load for each agent
            for row in agents:
                email = row['email']
                is_online = await get_agent_online_status(email, conn)
                if is_online:
                    chat_count = await get_agent_chat_count(email, conn)
                    online_users.append({
                        "email": email,
                        "role": "agent",
                        "is_online": True,
                        "active_sessions": chat_count
                    })

            # Check online status and load for each admin
            for row in admins:
                email = row['email']
                is_online = await get_agent_online_status(email, conn)
                if is_online:
                    chat_count = await get_agent_chat_count(email, conn)
                    online_users.append({
                        "email": email,
                        "role": "admin",
                        "is_online": True,
                        "active_sessions": chat_count
                    })

            return {
            "success": True,
            "agents": online_users
        }
    except Exception as db_error:
        logger.warning(f"Database unavailable for get_online_agents, returning empty list: {db_error}")
        # Return empty list instead of failing completely - allows frontend to continue working
        return {
            "success": True,
            "agents": []
        }


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
        
        # Check if user is a human agent or admin
        conn = await railway_db.get_connection()
        try:
            # Check if user is a confirmed human agent
            agent = await conn.fetchrow(
                """
                SELECT email FROM human_agents 
                WHERE email = $1 AND status = 'confirmed'
                """,
                user_email
            )
            
            # If not a human agent, check if user is an admin
            if not agent:
                admin = await conn.fetchrow(
                    """
                    SELECT email FROM admins 
                    WHERE email = $1 AND status = 'confirmed'
                    """,
                    user_email
                )
                if not admin:
                    raise HTTPException(status_code=403, detail="User is not a confirmed human agent or admin")
            
            # Update last activity timestamp for this agent
            # We'll use the session_assignments table to track activity
            # Create or update a heartbeat session to mark agent as online
            
            # Create a heartbeat session_id
            heartbeat_session_id = f"heartbeat_{user_email}"
            
            # Get or create the heartbeat chat_session
            heartbeat_cs = await conn.fetchrow(
                "SELECT id FROM chat_sessions WHERE session_id = $1",
                heartbeat_session_id
            )
            
            if not heartbeat_cs:
                # Create heartbeat chat session
                heartbeat_cs_id = await conn.fetchval(
                    """
                    INSERT INTO chat_sessions (session_id, is_active, metadata, last_activity_at, created_at)
                    VALUES ($1, TRUE, '{}'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    heartbeat_session_id
                )
            else:
                heartbeat_cs_id = heartbeat_cs['id']
            
            # Determine assignee type
            assignee_type = await conn.fetchval(
                """
                SELECT CASE 
                    WHEN EXISTS (SELECT 1 FROM admins WHERE email = $1 AND status = 'confirmed') 
                    THEN 'admin'
                    ELSE 'agent'
                END
                """,
                user_email
            )
            
            # Check if heartbeat assignment already exists
            existing = await conn.fetchval(
                "SELECT id FROM session_assignments WHERE session_id = $1",
                heartbeat_cs_id
            )
            
            if existing:
                # Update existing heartbeat entry
                await conn.execute(
                    """
                    UPDATE session_assignments 
                    SET assigned_at = CURRENT_TIMESTAMP, status = 'active', assignee_type = $1
                    WHERE session_id = $2
                    """,
                    assignee_type, heartbeat_cs_id
                )
            else:
                # Insert new heartbeat entry
                await conn.execute(
                    """
                    INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status, assigned_at)
                    VALUES ($1, $2, $3, 'active', CURRENT_TIMESTAMP)
                    """,
                    heartbeat_cs_id, user_email, assignee_type
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
    archive_status: Optional[str] = Query("active", description="Filter by archive status: active, closed, archived, transferred"),
    page: int = Query(1, ge=1, description="Page number for pagination"),
    limit: int = Query(50, ge=1, le=200, description="Number of sessions per page"),
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

    # Validate archive_status value
    valid_statuses = ['active', 'closed', 'archived', 'transferred']
    if archive_status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid archive_status: {archive_status}. Must be one of: {', '.join(valid_statuses)}")
    
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        # For human agents, we determine the agent from the authenticated user's email (from token)
        # The agent_id query parameter is ignored for security - we use user_email instead
        if role == 'human_agent':
            logger.info(f"Human agent {user_email} requesting their assigned chats (ignoring agent_id query parameter for security)")
        elif role in ['admin', 'user']:
            logger.info(f"{role.capitalize()} {user_email} requesting chat sessions (agent_id query param: {agent_id})")
        
        # Record heartbeat for human agents when they access chat log
        # This helps track which agents are online and available
        if role == 'human_agent':
            try:
                from services.configuration_service.main import get_db_connection
                async with get_db_connection() as heartbeat_conn:
                    # Always ensure heartbeat entry exists and is up-to-date
                    # This is the primary way we track that an agent is online
                    heartbeat_session_id = f"heartbeat_{user_email}"
                    
                    # Get or create the heartbeat chat_session
                    heartbeat_cs = await heartbeat_conn.fetchrow(
                        "SELECT id FROM chat_sessions WHERE session_id = $1",
                        heartbeat_session_id
                    )
                    
                    if not heartbeat_cs:
                        # Create heartbeat chat session
                        heartbeat_cs_id = await heartbeat_conn.fetchval(
                            """
                            INSERT INTO chat_sessions (session_id, is_active, metadata, last_activity_at, created_at)
                            VALUES ($1, TRUE, '{}'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            RETURNING id
                            """,
                            heartbeat_session_id
                        )
                    else:
                        heartbeat_cs_id = heartbeat_cs['id']
                    
                    # Determine assignee type
                    assignee_type = await heartbeat_conn.fetchval(
                        """
                        SELECT CASE 
                            WHEN EXISTS (SELECT 1 FROM admins WHERE email = $1 AND status = 'confirmed') 
                            THEN 'admin'
                            ELSE 'agent'
                        END
                        """,
                        user_email
                    )
                    
                    # Check if heartbeat assignment already exists
                    existing = await heartbeat_conn.fetchval(
                        "SELECT id FROM session_assignments WHERE session_id = $1",
                        heartbeat_cs_id
                    )
                    
                    if existing:
                        # Update existing heartbeat entry
                        await heartbeat_conn.execute(
                            """
                            UPDATE session_assignments 
                            SET assigned_at = CURRENT_TIMESTAMP, status = 'active', assignee_type = $1
                            WHERE session_id = $2
                            """,
                            assignee_type, heartbeat_cs_id
                        )
                        logger.debug(f"Updated heartbeat for agent {user_email}")
                    else:
                        # Insert new heartbeat entry
                        await heartbeat_conn.execute(
                            """
                            INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status, assigned_at)
                            VALUES ($1, $2, $3, 'active', CURRENT_TIMESTAMP)
                            """,
                            heartbeat_cs_id, user_email, assignee_type
                        )
                        logger.debug(f"Created heartbeat entry for agent {user_email}")
                    
                    logger.debug(f"Recorded activity for agent {user_email} via chat-sessions endpoint")
            except Exception as e:
                logger.warning(f"Could not record heartbeat for {user_email}: {e}")
        
        # For human agents, only return their own sessions
        # Use the authenticated user's email to ensure they can only see their own chats
        # SECURITY: Always use user_email from token, never trust agent_id query parameter
        if role == 'human_agent':
            # Always use the authenticated user's email for filtering (security)
            # Ignore agent_id parameter to prevent viewing other agents' chats
            agent_id = user_email
        # For admins and regular users, show all sessions
        elif role in ['admin', 'user']:
            agent_id = None  # Don't filter by agent for admins/users
        
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # Calculate offset for pagination
            offset = (page - 1) * limit

            # Build query based on role
            if role == 'human_agent' and agent_id:
                # Human agents: only their assigned sessions
                # Filter by assignee_email in session_assignments table to ensure they only see their chats
                # Also filter by archive_status
                sessions_data = await conn.fetch(
                    """
                    SELECT DISTINCT
                        cs.id,
                        cs.session_id,
                        cs.archive_status,
                        cs.conversation_summary,
                        COALESCE(cs.last_activity_at, cs.created_at, cs.updated_at, CURRENT_TIMESTAMP) as last_activity_at,
                        cs.created_at,
                        cs.metadata,
                        cs.is_active,
                        cs.sentiment
                    FROM chat_sessions cs
                    INNER JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE LOWER(sa.assignee_email) = LOWER($1)
                    AND sa.status IN ('waiting', 'active')
                    AND cs.archive_status = $2
                    ORDER BY COALESCE(cs.last_activity_at, cs.created_at, cs.updated_at, CURRENT_TIMESTAMP) DESC
                    LIMIT $3 OFFSET $4
                    """,
                    agent_id, archive_status, limit, offset
                )

                # Get total count for pagination
                total_count = await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT cs.id)
                    FROM chat_sessions cs
                    INNER JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE LOWER(sa.assignee_email) = LOWER($1)
                    AND sa.status IN ('waiting', 'active')
                    AND cs.archive_status = $2
                    """,
                    agent_id, archive_status
                )

                logger.info(f"Found {len(sessions_data)} sessions (page {page}, limit {limit}) for human agent {agent_id} with status {archive_status}")
            else:
                # Admins and users: all sessions filtered by archive_status
                sessions_data = await conn.fetch(
                    """
                    SELECT DISTINCT
                        cs.id,
                        cs.session_id,
                        cs.archive_status,
                        cs.conversation_summary,
                        cs.last_activity_at,
                        cs.created_at,
                        cs.metadata,
                        cs.is_active,
                        cs.sentiment,
                        sa.assignee_email as agent_email
                    FROM chat_sessions cs
                    LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE cs.archive_status = $1
                    ORDER BY cs.last_activity_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    archive_status, limit, offset
                )

                # Get total count for pagination
                total_count = await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT cs.id)
                    FROM chat_sessions cs
                    WHERE cs.archive_status = $1
                    """,
                    archive_status
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
                
                # Get assigned agent from session_row if available (for admin/user queries)
                assigned_agent = metadata.get('assigned_agent')
                if not assigned_agent and 'agent_email' in session_row and session_row['agent_email']:
                    assigned_agent = session_row['agent_email']
                if not assigned_agent and agent_id:
                    assigned_agent = agent_id
                
                # Use archive_status from database
                status = session_row.get('archive_status', 'active')

                # For backward compatibility, if status is 'active', check if session should be expired
                if status == 'active':
                    # Check if session has expired (5 minutes of inactivity)
                    last_activity = session_row['last_activity_at']
                    is_expired = False
                    if last_activity:
                        # Handle timezone-aware and naive datetime objects
                        if last_activity.tzinfo:
                            # Timezone-aware: convert to UTC naive for comparison
                            last_activity_naive = last_activity.replace(tzinfo=None) - (last_activity.utcoffset() or timedelta(0))
                        else:
                            # Already naive, assume UTC
                            last_activity_naive = last_activity

                        now_utc = datetime.utcnow()
                        time_diff = now_utc - last_activity_naive
                        # Expire if no activity for 5 minutes
                        is_expired = time_diff.total_seconds() > 300  # 5 minutes = 300 seconds

                    # Only keep as 'active' if:
                    # 1. Session is marked as active in DB
                    # 2. Has an assigned agent (human agent session)
                    # 3. Not expired (activity within last 5 minutes)
                    if not (session_row['is_active'] and assigned_agent and not is_expired):
                        status = 'closed'
                
                # If session expired, update it in the database
                if is_expired and session_row['is_active']:
                    try:
                        await conn.execute(
                            """
                            UPDATE chat_sessions 
                            SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                            WHERE id = $1
                            """,
                            session_db_id
                        )
                        logger.info(f"Marked expired session {session_id} as closed (no activity for 5+ minutes)")
                    except Exception as e:
                        logger.error(f"Error updating expired session: {e}")
                
                # Get sentiment from database
                sentiment = session_row.get('sentiment')

                # Compute feedback on-the-fly from chat_feedback table
                feedback_result = await conn.fetchrow(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                        COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
                    FROM chat_feedback
                    WHERE session_id = $1
                    """,
                    session_id
                )

                # Determine session feedback based on aggregated feedback
                if feedback_result and feedback_result['positive_count'] > 0 and feedback_result['negative_count'] == 0:
                    session_feedback = 'positive'
                elif feedback_result and feedback_result['negative_count'] > 0:
                    session_feedback = 'negative'
                else:
                    session_feedback = None

                # For backward compatibility, set customer_feedback and agent_feedback based on session_feedback
                # In the new schema, we don't distinguish between customer and agent feedback at the session level
                customer_feedback = session_feedback
                agent_feedback = session_feedback
                
                # If sentiment is not set and session is closed, analyze it
                if not sentiment and status == 'closed' and len(messages) > 0:
                    try:
                        from services.configuration_service.sentiment_analysis import analyze_and_store_sentiment
                        # Prepare messages for sentiment analysis
                        messages_for_analysis = [
                            {'sender': msg.sender, 'text': msg.text}
                            for msg in messages
                        ]
                        sentiment = await analyze_and_store_sentiment(session_id, messages_for_analysis, conn)
                    except Exception as e:
                        logger.warning(f"Could not analyze sentiment for session {session_id}: {e}")
                
                # Determine chat type
                chat_type = 'human-handoff' if assigned_agent else 'ai-chat'
                
                created_at = session_row.get('created_at')
                created_at_str = created_at.isoformat() if created_at else None
                
                sessions.append(ChatSessionResponse(
                    id=session_id,
                    customer_name=metadata.get('customer_name'),
                    customer_email=metadata.get('customer_email'),
                    status=status,
                    last_message_at=session_row['last_activity_at'].isoformat() if session_row['last_activity_at'] else datetime.now().isoformat(),
                    created_at=created_at_str,
                    assigned_agent=assigned_agent,
                    feedback=session_feedback,  # Backward compatibility
                    customer_feedback=customer_feedback,
                    agent_feedback=agent_feedback,
                    sentiment=sentiment,
                    chat_type=chat_type,
                    conversation_summary=session_row.get('conversation_summary'),
                    messages=messages
                ))
            
            # Calculate total pages
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


@router.patch("/chat-sessions/{session_id}/archive", response_model=dict)
async def archive_chat_session(
    session_id: str,
    archive_status: str = Query(..., description="New archive status: active, closed, archived, transferred"),
    current_user: dict = Depends(get_current_user)
):
    """
    Archive or change the status of a chat session.
    Only admins and human agents can archive sessions.
    """
    # Validate archive_status
    valid_statuses = ['active', 'closed', 'archived', 'transferred']
    if archive_status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"Invalid archive_status: {archive_status}. Must be one of: {', '.join(valid_statuses)}")

    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")

        # Check if user is admin or human agent
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            user_role = await conn.fetchval(
                """
                SELECT CASE
                    WHEN EXISTS (SELECT 1 FROM admins WHERE email = $1 AND status = 'confirmed') THEN 'admin'
                    WHEN EXISTS (SELECT 1 FROM human_agents WHERE email = $1 AND status = 'confirmed') THEN 'human_agent'
                    ELSE 'user'
                END
                """,
                user_email
            )

            if user_role not in ['admin', 'human_agent']:
                raise HTTPException(status_code=403, detail="Only admins and human agents can archive sessions")

            # Update the session status
            result = await conn.execute(
                """
                UPDATE chat_sessions
                SET archive_status = $1, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = $2
                """,
                archive_status, session_id
            )

            if result == "UPDATE 0":
                raise HTTPException(status_code=404, detail="Session not found")

            logger.info(f"Session {session_id} status changed to {archive_status} by {user_email}")

            return {
                "success": True,
                "message": f"Session status changed to {archive_status}",
                "session_id": session_id,
                "archive_status": archive_status
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error archiving session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error archiving session: {str(e)}")


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
            
            # Broadcast message via SSE to customer
            message_data = {
                "type": "agent_message",
                "message_id": message_id,
                "text": request.text,
                "sender": "agent",
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "agent_email": user_email
            }
            await connection_manager.broadcast_to_session(message_data, session_id)
            
            return SendMessageResponse(
                message_id=message_id,
                success=True
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending agent message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send message")


# SSE endpoint for agents
@router.get("/chat-sessions/{session_id}/events")
async def agent_chat_sse(session_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """SSE endpoint for agent chat events."""
    try:
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
                        # Send ping to keep connection alive
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting up agent SSE: {e}")
        raise HTTPException(status_code=500, detail="Failed to establish SSE connection")


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


@router.post("/chat-sessions/{session_id}/transfer", response_model=dict)
async def transfer_chat_session(
    session_id: str,
    target_agent_email: str = Query(..., description="Email of the agent or admin to transfer to"),
    current_user: dict = Depends(get_current_user)
):
    """
    Transfer a chat session to another agent or admin.
    Accessible by both human agents and admins.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
            
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Check if current user has permission (must be confirmed agent or admin)
            is_agent = await conn.fetchval(
                "SELECT COUNT(*) FROM human_agents WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            
            if not is_agent and not is_admin:
                raise HTTPException(status_code=403, detail="Only confirmed agents or admins can transfer chats")
                
            # Check if target agent exists and is confirmed
            target_is_agent = await conn.fetchval(
                "SELECT COUNT(*) FROM human_agents WHERE email = $1 AND status = 'confirmed'",
                target_agent_email
            )
            target_is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                target_agent_email
            )
            
            if not target_is_agent and not target_is_admin:
                raise HTTPException(status_code=400, detail="Target user is not a confirmed agent or admin")
                
            # Perform the transfer
            await assign_chat_to_agent(session_id, target_agent_email, conn)
            
            # Broadcast transfer message via WebSocket
            transfer_message = {
                "type": "chat_transferred",
                "session_id": session_id,
                "transferred_to": target_agent_email,
                "transferred_by": user_email,
                "timestamp": datetime.utcnow().isoformat(),
                "text": "Chat has been transferred to another support agent"
            }
            await connection_manager.broadcast_to_session(transfer_message, session_id)
            
            # Also add a system message to the chat
            session_row = await conn.fetchrow(
                "SELECT id FROM chat_sessions WHERE session_id = $1",
                session_id
            )
            if session_row:
                await conn.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content)
                    VALUES ($1, 'system', $2)
                    """,
                    session_row['id'], f"Chat transferred to another support agent"
                )
            
            return {
                "success": True,
                "message": f"Chat transferred to {target_agent_email}",
                "assigned_agent": target_agent_email
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error transferring chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/chat-sessions/{session_id}", response_model=dict)
async def update_chat_session(
    session_id: str,
    status: Optional[str] = Query(None, description="Session status: 'active', 'waiting', or 'closed'"),
    assigned_agent: Optional[str] = Query(None, description="Assigned agent email (set to empty string to remove)"),
    feedback: Optional[str] = Query(None, description="Session feedback: 'positive' or 'negative'"),
    user_type: Optional[str] = Query(None, description="User type providing feedback: 'customer' or 'agent'"),
    current_user: dict = Depends(get_current_user)
):
    """
    Update a chat session (e.g., close session, remove assigned agent, update feedback).
    Allows both customers and agents/admins to end the session and provide feedback.
    """
    try:
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # Get session database ID
            session_row = await conn.fetchrow(
                "SELECT id, session_id, metadata FROM chat_sessions WHERE session_id = $1",
                session_id
            )
            
            if not session_row:
                raise HTTPException(status_code=404, detail="Chat session not found")
            
            session_db_id = session_row['id']
            
            # Parse metadata - it might be a JSON string or already a dict
            raw_metadata = session_row['metadata']
            if raw_metadata is None:
                current_metadata = {}
            elif isinstance(raw_metadata, str):
                try:
                    current_metadata = json.loads(raw_metadata)
                except (json.JSONDecodeError, TypeError):
                    current_metadata = {}
            elif isinstance(raw_metadata, dict):
                current_metadata = raw_metadata
            else:
                current_metadata = {}
            
            # Build update query dynamically based on provided parameters
            updates = []
            params = []
            param_index = 1
            
            if status is not None:
                updates.append(f"is_active = ${param_index}")
                params.append(status != 'closed')
                param_index += 1
            
            if assigned_agent is not None:
                # Update metadata to remove assigned agent
                if assigned_agent == '' or assigned_agent is None:
                    # Remove assigned agent from metadata
                    if 'assigned_agent' in current_metadata:
                        del current_metadata['assigned_agent']
                    updates.append(f"metadata = ${param_index}::jsonb")
                    params.append(json.dumps(current_metadata))
                    param_index += 1
                else:
                    # Set assigned agent in metadata
                    current_metadata['assigned_agent'] = assigned_agent
                    updates.append(f"metadata = ${param_index}::jsonb")
                    params.append(json.dumps(current_metadata))
                    param_index += 1
            
            # Handle feedback with user_type
            if feedback is not None and user_type is not None:
                # Store feedback in metadata with user_type key
                feedback_key = f"{user_type}_feedback"
                current_metadata[feedback_key] = feedback
                updates.append(f"metadata = ${param_index}::jsonb")
                params.append(json.dumps(current_metadata))
                param_index += 1

                # Note: session_feedback column has been removed - feedback is computed on-the-fly
            
            if not updates:
                raise HTTPException(status_code=400, detail="No updates provided")
            
            # Always update updated_at
            updates.append(f"updated_at = CURRENT_TIMESTAMP")
            
            # Add session_db_id as last parameter
            params.append(session_db_id)
            
            query = f"""
                UPDATE chat_sessions 
                SET {', '.join(updates)}
                WHERE id = ${param_index}
            """
            
            await conn.execute(query, *params)
            
            logger.info(f"Session {session_id} updated by {user_email}: status={status}, assigned_agent={assigned_agent}, feedback={feedback}, user_type={user_type}")
            
            # If session is being closed, analyze sentiment if not already analyzed
            if status == 'closed':
                try:
                    # Check if sentiment is already set
                    current_sentiment = await conn.fetchval(
                        "SELECT sentiment FROM chat_sessions WHERE id = $1",
                        session_db_id
                    )
                    
                    # If sentiment is not set, analyze it
                    if not current_sentiment:
                        # Get all messages for sentiment analysis
                        messages_data = await conn.fetch(
                            """
                            SELECT role, content
                            FROM chat_messages
                            WHERE session_id = $1
                            ORDER BY created_at ASC
                            """,
                            session_db_id
                        )
                        
                        if messages_data:
                            from services.configuration_service.sentiment_analysis import analyze_and_store_sentiment
                            # Prepare messages for sentiment analysis
                            messages_for_analysis = [
                                {
                                    'sender': 'bot' if msg['role'] == 'assistant' else msg['role'],
                                    'text': msg['content']
                                }
                                for msg in messages_data
                            ]
                            sentiment_result = await analyze_and_store_sentiment(session_id, messages_for_analysis, conn)
                            if sentiment_result:
                                logger.info(f"Successfully analyzed and stored sentiment '{sentiment_result}' for closed session {session_id}")
                            else:
                                logger.warning(f"Sentiment analysis returned None for closed session {session_id}")

                            # Generate and store conversation summary
                            try:
                                from services.configuration_service.sentiment_analysis import generate_and_store_conversation_summary
                                summary_result = await generate_and_store_conversation_summary(session_id, messages_for_analysis, conn)
                                if summary_result:
                                    logger.info(f"Successfully generated and stored conversation summary for closed session {session_id}")
                                else:
                                    logger.warning(f"Conversation summarization returned None for closed session {session_id}")
                            except Exception as e:
                                logger.warning(f"Could not generate conversation summary for closed session {session_id}: {e}")
                except Exception as e:
                    logger.warning(f"Could not analyze sentiment for closed session {session_id}: {e}")
            
            # If session is being closed, broadcast a message to all connected clients
            if status == 'closed' and assigned_agent == '':
                # Determine if the user ending the session is an agent or customer
                # Check if user is a human agent
                is_agent = await conn.fetchval(
                    "SELECT COUNT(*) FROM human_agents WHERE email = $1 AND status = 'confirmed'",
                    user_email
                )
                
                # Check if user is an admin (admins can also end sessions)
                is_admin = await conn.fetchval(
                    "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                    user_email
                )
                
                # Determine who ended the session
                ended_by = 'human agent' if (is_agent or is_admin) else 'customer'
                
                # Broadcast session ended message to all connected clients
                session_ended_message = {
                    "type": "session_ended",
                    "session_id": session_id,
                    "text": f"Session has been ended by the {ended_by}.",
                    "ended_by": ended_by,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
                try:
                    await connection_manager.broadcast_to_session(session_ended_message, session_id)
                    logger.info(f"Broadcasted session ended message to session {session_id}: ended by {ended_by}")
                except Exception as e:
                    logger.error(f"Error broadcasting session ended message: {e}")
            
            return {
                'success': True,
                'message': 'Session updated successfully'
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating chat session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating session: {str(e)}")


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
            # Try to get hil_enabled from configuration_metadata, but default to True if not set
            try:
                config = await conn.fetchrow(
                    "SELECT hil_enabled FROM configuration_metadata WHERE id = 1"
                )
                
                # Default to enabled if not set (hil_enabled can be NULL, which means enabled by default)
                hil_enabled = config.get('hil_enabled') if config and config.get('hil_enabled') is not None else True
            except Exception as e:
                # If table/column doesn't exist, default to True
                if 'configuration_metadata' in str(e) or 'hil_enabled' in str(e) or 'column' in str(e).lower():
                    logger.warning(f"configuration_metadata table or hil_enabled column not found. Please run migration script. Defaulting to True.")
                    hil_enabled = True
                else:
                    # For other errors, default to True
                    logger.error(f"Error checking hil_enabled: {e}")
                    hil_enabled = True
            
            if not hil_enabled:
                raise HTTPException(
                    status_code=503, 
                    detail="Human agent support is currently disabled"
                )
            
            # Use load balancing to assign chat to agent with least active chats
            assigned_agent = await assign_chat_with_load_balancing(session_id, conn)
            
            if not assigned_agent:
                # Check if there are any confirmed agents at all
                total_agents = await conn.fetchval(
                    "SELECT COUNT(*) FROM human_agents WHERE status = 'confirmed'"
                ) or 0
                
                if total_agents == 0:
                    error_detail = "No human agents are configured. Please contact your administrator to set up human agents."
                else:
                    # Check if any agents are online
                    online_count = await conn.fetchval(
                        """
                        SELECT COUNT(DISTINCT sa.assignee_email)
                        FROM session_assignments sa
                        WHERE sa.assigned_at > NOW() - INTERVAL '30 minutes'
                        AND sa.assignee_email IN (SELECT email FROM human_agents WHERE status = 'confirmed')
                        """
                    ) or 0
                    
                    if online_count == 0:
                        error_detail = "No human agents are currently online. Agents need to access the chat log to be marked as online. Please try again later."
                    else:
                        error_detail = "No available agents to assign chat. Please try again later."
                
                logger.warning(f"Failed to assign chat {session_id}: {error_detail}")
                raise HTTPException(
                    status_code=503, 
                    detail=error_detail
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


@public_chat_router.patch("/{session_id}/end", response_model=dict)
async def end_customer_session(
    session_id: str,
    request: Request
):
    """
    End a chat session from the customer side.
    This endpoint is called when a customer closes the chat window.
    No authentication required - called from public chatbot widget.
    """
    try:
        # Use get_db_connection context manager to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        
        async with get_db_connection() as conn:
            # Get session database ID
            session_row = await conn.fetchrow(
                "SELECT id, metadata FROM chat_sessions WHERE session_id = $1",
                session_id
            )
            
            if not session_row:
                raise HTTPException(status_code=404, detail="Chat session not found")
            
            session_db_id = session_row['id']
            
            # Parse metadata
            raw_metadata = session_row['metadata']
            if raw_metadata is None:
                current_metadata = {}
            elif isinstance(raw_metadata, str):
                try:
                    current_metadata = json.loads(raw_metadata)
                except (json.JSONDecodeError, TypeError):
                    current_metadata = {}
            elif isinstance(raw_metadata, dict):
                current_metadata = raw_metadata
            else:
                current_metadata = {}
            
            # Update session status to closed and remove assigned agent
            if 'assigned_agent' in current_metadata:
                del current_metadata['assigned_agent']
            
            # Update the session
            await conn.execute(
                """
                UPDATE chat_sessions 
                SET is_active = false, 
                    metadata = $1, 
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = $2
                """,
                json.dumps(current_metadata), session_db_id
            )
            
            logger.info(f"Customer ended session {session_id}")
            
            # Broadcast session ended message to all connections in this session
            session_ended_message = {
                'type': 'session_ended',
                'session_id': session_id,
                'ended_by': 'customer',
                'text': 'The session has ended by the customer.',
                'timestamp': time.time()
            }
            
            await connection_manager.broadcast_to_session(session_ended_message, session_id)
            logger.info(f"Broadcasted session ended message to session {session_id}: ended by customer")
            
            return {
                "success": True,
                "message": "Session ended successfully",
                "session_id": session_id
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending customer session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error ending session: {str(e)}")


# SSE endpoints for real-time chat
@router.get("/chat-sessions/{session_id}/events")
async def sse_agent_chat(session_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """
    SSE endpoint for agents to connect to a chat session.
    Requires authentication.
    """
    from fastapi.responses import StreamingResponse
    import json

    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")

    # Verify agent has access to this session
    from services.configuration_service.main import get_db_connection
    async with get_db_connection() as conn:
        # Check if agent is assigned to this session
        assigned = await conn.fetchrow(
            """
            SELECT sa.assignee_email FROM session_assignments sa
            INNER JOIN chat_sessions cs ON sa.session_id = cs.id
            WHERE cs.session_id = $1 AND sa.assignee_email = $2
            """,
            session_id, user_email
        )
        if not assigned:
            # Check if user is admin
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            if not is_admin:
                raise HTTPException(status_code=403, detail="Access denied")

    # Create SSE response
    async def event_generator():
        # Connect to session
        await connection_manager.connect(request, session_id, 'agent')

        try:
            while True:
                # Wait for next message
                message = await connection_manager.get_next_message(request)
                if message:
                    # Format as SSE event
                    if message.get('type') == 'ping':
                        yield f"event: ping\ndata: {json.dumps(message)}\n\n"
                    else:
                        yield f"data: {json.dumps(message)}\n\n"

        except Exception as e:
            logger.error(f"Error in agent SSE: {e}")
        finally:
            # Disconnect from session
            try:
                await connection_manager.disconnect(request)
            except Exception as e:
                logger.error(f"Error disconnecting agent SSE: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        }
    )


@public_chat_router.get("/{session_id}/events")
async def sse_customer_chat(session_id: str, request: Request):
    """
    SSE endpoint for customers to connect to a chat session.
    No authentication required for customers.
    """
    from fastapi.responses import StreamingResponse
    import json

    logger.info(f"🔍 Customer SSE connection attempt for session: {session_id}")
    logger.info(f"🔍 Request headers: {dict(request.headers)}")

    # Create SSE response
    async def event_generator():
        try:
            # Connect customer to session
            logger.info(f"🔍 Connecting customer to session: {session_id}")
            await connection_manager.connect(request, session_id, 'customer')
            logger.info(f"✅ Customer connected to SSE for session: {session_id}")

            try:
                while True:
                    # Wait for next message
                    message = await connection_manager.get_next_message(request)
                    if message:
                        # Format as SSE event
                        if message.get('type') == 'ping':
                            yield f"event: ping\ndata: {json.dumps(message)}\n\n"
                        else:
                            yield f"data: {json.dumps(message)}\n\n"

            except Exception as e:
                logger.error(f"❌ Error in customer SSE event loop: {e}")
        finally:
            # Disconnect from session
            try:
                await connection_manager.disconnect(request)
                logger.info(f"🔌 Customer disconnected from SSE for session: {session_id}")
            except Exception as e:
                logger.error(f"❌ Error disconnecting customer SSE: {e}")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control",
        }
    )

