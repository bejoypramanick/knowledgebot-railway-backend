import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from fastapi import HTTPException

from configuration.dao.chat_log_dao import ChatLogDAO
from configuration.dao.auth_dao import AuthDAO
from shared.otel_logger import get_otel_logger
logger = get_otel_logger("chat_log_service", "configuration")

# Import Redis Pub/Sub broadcast functions
from shared.redis_pubsub_manager import (
    broadcast_event_to_agent,
    broadcast_event_for_session
)

class ChatLogService:
    """Service layer for chat log operations"""

    def __init__(self):
        self.dao = ChatLogDAO()
        self.auth_dao = AuthDAO()
        self.connection_manager = None  # Placeholder - should be initialized if needed for websockets

    # --- Cached identity resolution methods (Redis DB4 cache + DB fallback) ---

    async def get_user_id_by_email_cached(self, email: str) -> Optional[int]:
        """Get user ID from email, using Redis cache with DB fallback."""
        from shared.redis_agent_cache import get_cached_user_id, set_cached_user_id
        cached = await get_cached_user_id(email)
        if cached is not None:
            return cached
        user_id = await self.dao.get_user_id_by_email(email)
        if user_id is not None:
            await set_cached_user_id(email, user_id)
        return user_id

    async def get_email_by_user_id_cached(self, user_id: int) -> Optional[str]:
        """Get email from user ID, using Redis cache with DB fallback."""
        from shared.redis_agent_cache import get_cached_user_email, set_cached_user_id
        cached = await get_cached_user_email(user_id)
        if cached is not None:
            return cached
        email = await self.dao.get_email_by_user_id(user_id)
        if email is not None:
            await set_cached_user_id(email, user_id)  # Caches both directions
        return email

    async def get_admin_ids_cached(self) -> List[int]:
        """Get all admin IDs, using Redis cache with DB fallback."""
        from shared.redis_agent_cache import get_cached_admin_ids, set_cached_admin_ids
        cached = await get_cached_admin_ids()
        if cached is not None:
            return cached
        ids = await self.dao.get_all_admin_ids()
        await set_cached_admin_ids(ids)
        return ids

    async def get_assigned_agent_id_cached(self, session_uuid: str, numeric_session_id: int) -> Optional[int]:
        """Get assigned agent ID, using Redis DB4 cache with DB fallback."""
        from shared.redis_agent_cache import get_assigned_agent, set_assigned_agent
        cached = await get_assigned_agent(session_uuid)
        if cached:
            try:
                return int(cached)
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Cached agent value is non-numeric (legacy): '{cached}' - falling through to DB lookup")
        agent_id = await self.dao.get_assigned_agent_id(numeric_session_id)
        if agent_id:
            await set_assigned_agent(session_uuid, agent_id)
            logger.info(f"Cached agent assignment (DB 4): {numeric_session_id} -> ID {agent_id}")
        return agent_id

    async def get_session_uuid(self, numeric_session_id: int) -> Optional[str]:
        """Get session UUID from numeric session ID."""
        return await self.dao.get_session_uuid(numeric_session_id)

    async def resolve_session_id(self, session_id_raw: str) -> tuple[int, Optional[str]]:
        """Resolve session_id (numeric or UUID) to (numeric_id, uuid) tuple.

        Accepts both numeric IDs and UUIDs. Returns (numeric_id, session_uuid).
        Raises HTTPException if session not found.
        """
        session_id_str = str(session_id_raw)
        if session_id_str.isdigit():
            numeric_id = int(session_id_str)
            session_uuid = await self.dao.get_session_uuid(numeric_id)
            if not session_uuid:
                raise HTTPException(status_code=404, detail=f"Session {numeric_id} not found")
            return numeric_id, session_uuid
        else:
            numeric_id = await self.dao.get_session_numeric_id(session_id_str)
            if not numeric_id:
                raise HTTPException(status_code=404, detail=f"Session not found: {session_id_str}")
            return numeric_id, session_id_str

    async def resolve_sender_identity(self, sender_id_raw: Optional[str], header_email: str) -> tuple[Optional[int], Optional[str]]:
        """Resolve sender numeric ID and email from agent_id body param or X-User-Email header.

        Returns:
            (sender_id_int, sender_email) tuple. Either may be None if resolution fails.
        """
        sender_id_int = None
        sender_email = None

        if sender_id_raw and sender_id_raw != 'system':
            try:
                sender_id_int = int(sender_id_raw)
            except (ValueError, TypeError):
                # agent_id is non-numeric (could be email)
                sender_id_int = await self.get_user_id_by_email_cached(str(sender_id_raw))
                if sender_id_int:
                    sender_email = str(sender_id_raw)

        # Fallback to X-User-Email header
        if sender_id_int is None and header_email:
            sender_id_int = await self.get_user_id_by_email_cached(header_email)
            if sender_id_int:
                sender_email = header_email
                logger.info(f"🔍 Resolved sender from X-User-Email header: {header_email} → ID {sender_id_int}")

        # Get email if we have ID but no email yet
        if sender_id_int and not sender_email:
            sender_email = await self.get_email_by_user_id_cached(sender_id_int) or f"agent-{sender_id_int}"

        return sender_id_int, sender_email

    async def get_all_chat_logs(self) -> List[Dict[str, Any]]:
        """Get all chat logs"""
        try:
            return await self.dao.get_all_chat_logs()
        except Exception as e:
            logger.error(f"Error getting all chat logs: {e}")
            raise

    async def delete_chat_log(self, session_id: int, user_email: str) -> Dict[str, Any]:
        """Delete a chat log"""
        try:
            return await self.dao.delete_chat_log(session_id)
        except Exception as e:
            logger.error(f"Error deleting chat log {session_id}: {e}")
            raise

    async def assign_chat_to_agent(self, session_id: int, agent_email: str):
        """Assign chat to specific agent"""
        try:
            # session_id is already numeric (resolved by API Gateway)
            session_db_id = session_id

            # Validate that session exists before creating assignment
            session = await self.dao.get_session_by_id_with_messages(session_db_id)
            if not session:
                logger.error(f"❌ Cannot assign chat: session {session_db_id} does not exist")
                raise HTTPException(status_code=404, detail=f"Session {session_db_id} not found")
            
            # Get session UUID for caching and broadcasting
            session_uuid = session.get('session_id')  # UUID format
            
            # Get agent user ID for broadcasting
            agent_id = await self.dao.get_user_id_by_email(agent_email)
            if not agent_id:
                logger.error(f"❌ Could not get user ID for agent {agent_email}")
                raise HTTPException(status_code=400, detail=f"Invalid agent email: {agent_email}")
            
            # Update metadata with customer display name and assigned agent
            metadata = session.get('metadata') or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except (json.JSONDecodeError, TypeError):
                    metadata = {}
            
            # Set customer_name to "User-<numeric_id>" if not already set
            if not metadata.get('customer_name'):
                metadata['customer_name'] = f"User-{session_db_id}"
            
            # Store assigned_agent in metadata for persistence
            metadata['assigned_agent'] = agent_email
            await self.dao.update_chat_session_metadata(session_db_id, metadata)
            logger.info(f"✅ Updated metadata: customer_name='User-{session_db_id}', assigned_agent='{agent_email}' for session {session_uuid}")
            
            logger.info(f"Chat session {session_db_id} assigned to agent {agent_email} (ID: {agent_id})")
            assignee_type = "agent"
            existing = await self.dao.get_session_assignment(session_db_id)
            if existing:
                await self.dao.update_session_assignment(session_db_id, agent_email, assignee_type, status='active')
            else:
                await self.dao.create_session_assignment(session_db_id, agent_email, assignee_type, status='active')
            
            # Cache the agent assignment in Redis DB 4 (TTL: 1 hour)
            from shared.redis_agent_cache import set_assigned_agent
            from shared.redis_pubsub_manager import broadcast_event_to_session
            await set_assigned_agent(session_uuid, agent_id)
            logger.info(f"Cached agent assignment (DB 4): {session_uuid} -> {agent_id}")
            
            # CRITICAL: Broadcast to BOTH agent AND customer
            assignment_event = {
                "type": "chat_assigned",
                "session_id": session_uuid,  # CRITICAL: Use UUID for SSE channel matching
                "numeric_session_id": str(session_db_id),  # Include numeric ID for reference
                "agent_email": agent_email,
                "agent_id": agent_id,
                "assignee_type": assignee_type,
                "status": "active",
                "message": "New chat assigned to you",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Send to agent (so it appears in their ChatLog) - use user ID
            await broadcast_event_to_agent(agent_id, assignment_event)
            logger.info(f"📤 Sent assignment notification to agent {agent_email} (ID: {agent_id}) via Redis Pub/Sub")
            
            # Send to customer (so UI blocks AI and enables agent chat)
            # CRITICAL: Use session UUID, not numeric ID
            await broadcast_event_to_session(session_uuid, assignment_event)
            logger.info(f"📤 Sent assignment notification to customer session {session_uuid} via Redis Pub/Sub")
            
        except Exception as e:
            logger.error(f"Error assigning chat to agent: {e}", exc_info=True)
            raise

    async def get_agent_online_status(self, agent_id: int) -> bool:
        """
        Check if agent is online by checking Redis presence key.
        Agent is considered online if they have an active SSE connection.
        The presence key is set when agent connects and has a TTL of 60 seconds.
        
        Args:
            agent_id: User ID of the agent (from users table)
        """
        try:
            from shared.redis_pubsub_manager import get_pubsub_redis
            redis_client = await get_pubsub_redis()
            
            # Check if agent has an active presence key (using user ID)
            presence_key = f"agent:online:{agent_id}"
            is_online = await redis_client.exists(presence_key)
            
            logger.info(f"🔍 [ONLINE_CHECK] Agent ID {agent_id} online status: {bool(is_online)}")
            return bool(is_online)
        except Exception as e:
            logger.error(f"❌ Error checking agent online status for agent ID {agent_id}: {e}")
            # If Redis check fails, assume agent is offline (fail-safe)
            return False 

    async def get_agent_chat_count(self, agent_email: str) -> int:
        """Get the number of active chats assigned to an agent."""
        try:
            return await self.dao.get_agent_chat_count(agent_email)
        except Exception as e:
            logger.error(f"Error getting agent chat count: {e}")
            return 0

    async def assign_chat_with_load_balancing(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Assign a chat to an available agent using load balancing (numeric ID only).
        
        Returns:
            Dict with 'email' and 'id' keys, or None if no agents available
        """
        try:
            logger.info(f"🔍 [LOAD_BALANCE] Starting load balancing for session {session_id}")
            
            # Step 1: Get all human agents
            agent_emails = await self.dao.get_all_human_agents()
            logger.info(f"🔍 [LOAD_BALANCE] Found {len(agent_emails)} human agents: {agent_emails}")
            
            agent_loads = []
            
            if agent_emails:
                logger.info(f"🔍 [LOAD_BALANCE] Checking availability of {len(agent_emails)} human agents")
                for email in agent_emails:
                    # Get user ID for this agent
                    agent_id = await self.dao.get_user_id_by_email(email)
                    if not agent_id:
                        logger.warning(f"⚠️ [LOAD_BALANCE] Could not get user ID for agent {email}")
                        continue
                    
                    is_online = await self.get_agent_online_status(agent_id)
                    logger.info(f"🔍 [LOAD_BALANCE] Agent {email} (ID: {agent_id}) online status: {is_online}")
                    
                    if is_online:
                        chat_count = await self.get_agent_chat_count(email)
                        logger.info(f"🔍 [LOAD_BALANCE] Agent {email} (ID: {agent_id}) has {chat_count} active chats")
                        agent_loads.append({'email': email, 'id': agent_id, 'chat_count': chat_count})
            else:
                logger.warning(f"⚠️ [LOAD_BALANCE] No human agents found in database")
            
            # Step 2: If no human agents, try admins
            if not agent_loads:
                logger.info(f"🔍 [LOAD_BALANCE] No available human agents, checking admins")
                admin_emails = await self.dao.get_all_admins()
                logger.info(f"🔍 [LOAD_BALANCE] Found {len(admin_emails)} admins: {admin_emails}")
                
                for email in admin_emails:
                    # Get user ID for this admin
                    admin_id = await self.dao.get_user_id_by_email(email)
                    if not admin_id:
                        logger.warning(f"⚠️ [LOAD_BALANCE] Could not get user ID for admin {email}")
                        continue
                    
                    is_online = await self.get_agent_online_status(admin_id)
                    logger.info(f"🔍 [LOAD_BALANCE] Admin {email} (ID: {admin_id}) online status: {is_online}")
                    
                    if is_online:
                        chat_count = await self.get_agent_chat_count(email)
                        logger.info(f"🔍 [LOAD_BALANCE] Admin {email} (ID: {admin_id}) has {chat_count} active chats")
                        agent_loads.append({'email': email, 'id': admin_id, 'chat_count': chat_count})
            
            # Step 3: Check if we found any agents
            if not agent_loads:
                logger.error(f"❌ [LOAD_BALANCE] No available agents or admins found for session {session_id}")
                logger.error(f"❌ [LOAD_BALANCE] Human agents in DB: {agent_emails}")
                logger.error(f"❌ [LOAD_BALANCE] Admins in DB: {admin_emails if 'admin_emails' in locals() else 'Not checked'}")
                return None
            
            # Step 4: Sort by chat count and assign to least busy agent
            agent_loads.sort(key=lambda x: x['chat_count'])
            assigned_agent_info = agent_loads[0]
            assigned_agent = assigned_agent_info['email']
            assigned_agent_id = assigned_agent_info['id']
            assigned_is_admin = assigned_agent in (await self.dao.get_all_admins()) if agent_loads else False

            logger.info(f"✅ [LOAD_BALANCE] Selected agent {assigned_agent} (ID: {assigned_agent_id}) with {agent_loads[0]['chat_count']} chats")
            logger.info(f"🔍 [LOAD_BALANCE] Agent type: {'ADMIN' if assigned_is_admin else 'HUMAN_AGENT'}")
            logger.info(f"🔍 [LOAD_BALANCE] All available agents: {agent_loads}")
            logger.info(f"📊 [LOAD_BALANCE] Assignment details: human_agents_found={len(agent_emails)}, admins_found={len(admin_emails) if 'admin_emails' in locals() else 'N/A'}, selected={assigned_agent} (ID: {assigned_agent_id})")

            # Step 5: Assign the chat
            await self.assign_chat_to_agent(session_id, assigned_agent)
            logger.info(f"✅ [LOAD_BALANCE] Successfully assigned session {session_id} to {assigned_agent} (ID: {assigned_agent_id}) ({'ADMIN' if assigned_is_admin else 'HUMAN_AGENT'})")
            
            return {'email': assigned_agent, 'id': assigned_agent_id}
        except Exception as e:
            logger.error(f"❌ [LOAD_BALANCE] Error in load balancing for session {session_id}: {e}", exc_info=True)
            return None

    async def record_heartbeat(self, user_email: str):
        """
        Record heartbeat for an agent or admin.
        
        NOTE: This is a lightweight presence indicator - does NOT create sessions.
        Simply updates the last activity timestamp for the agent.
        Actual agent presence can be tracked via:
        - SSE connection status (/admin/events)
        - Last API call timestamp
        - Session assignments with recent activity
        """
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_agent"] and not roles["is_admin"]:
            raise HTTPException(status_code=403, detail="User is not a human agent or admin")

        # Heartbeat is now a no-op - presence is tracked via SSE connections
        # and session assignments, not via fake heartbeat sessions
        logger.debug(f"💓 Heartbeat received from {user_email} (no session created)")
        return True

    async def get_chat_sessions(self, role: str, user_email: str, archive_status: str, page: int, limit: int, agent_id: Optional[str] = None, offset: Optional[int] = None):
        """Get chat sessions with pagination, filtering, and efficiency."""
        import time
        start_time = time.time()
        logger.info(f"🔍 [CHATLOG] Starting get_chat_sessions - role={role}, status={archive_status}, page={page}, limit={limit}")
        
        # Get current user's ID for is_assigned_to_me comparison
        current_user_id = None
        if user_email:
            try:
                current_user_id = await self.dao.get_user_id_by_email(user_email)
            except Exception as e:
                logger.warning(f"⚠️ Could not get user ID for {user_email}: {e}")
        
        # Use provided offset or calculate from page
        if offset is None:
            offset = (page - 1) * limit
        
        step_start = time.time()
        if role == 'human_agent':
            await self.record_heartbeat(user_email)
            sessions_data = await self.dao.get_sessions_for_agent(user_email, archive_status, limit, offset)
            total_count = await self.dao.count_sessions_for_agent(user_email, archive_status)
        else:
            sessions_data = await self.dao.get_all_sessions(archive_status, limit, offset)
            total_count = await self.dao.count_all_sessions(archive_status)
        
        step_duration = time.time() - step_start
        logger.info(f"⏱️ [CHATLOG] Step 1: Fetched {len(sessions_data) if sessions_data else 0} sessions in {step_duration:.2f}s")

        if not sessions_data:
            logger.info(f"✅ [CHATLOG] No sessions found, returning empty list (total time: {time.time() - start_time:.2f}s)")
            return [], total_count

        session_db_ids = [int(s['id']) if isinstance(s['id'], str) else s['id'] for s in sessions_data]
        logger.info(f"⚡ [CHATLOG] Fetching latest messages for {len(session_db_ids)} sessions: {session_db_ids[:5]}{'...' if len(session_db_ids) > 5 else ''}")

        # Fetch latest messages for ALL sessions in ONE query (optimized)
        step_start = time.time()
        latest_messages = await self.dao.get_latest_messages_batch(session_db_ids)
        step_duration = time.time() - step_start
        logger.info(f"⏱️ [CHATLOG] Step 2: Loaded latest messages for {len(latest_messages)} sessions in {step_duration:.2f}s")

        # Get all session IDs for batch feedback query (uses session_id UUID)
        session_ids = [s['session_id'] for s in sessions_data]
        logger.info(f"⚡ [CHATLOG] Fetching feedback for {len(session_ids)} sessions")
        
        # OPTIMIZATION: Fetch feedback counts for all sessions in one query
        step_start = time.time()
        batch_feedback_counts = await self.dao.get_batch_feedback_counts(session_ids)
        step_duration = time.time() - step_start
        logger.info(f"⏱️ [CHATLOG] Step 3: Loaded feedback counts in {step_duration:.2f}s")

        formatted_sessions = []
        for session_row in sessions_data:
            session_id = session_row['session_id']
            # Ensure session_db_id is an integer (may be string from database)
            session_db_id = int(session_row['id']) if isinstance(session_row['id'], str) else session_row['id']

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

            # Include all messages for the session (needed for chat detail view)
            from ..schemas.chat_log_schemas import ChatMessageResponse
            all_session_messages = await self.dao.get_session_messages(session_db_id)
            messages = [
                ChatMessageResponse(
                    id=str(msg['id']),
                    text=msg['content'],
                    sender=msg['role'],
                    timestamp=msg['created_at'].isoformat() if msg['created_at'] else datetime.utcnow().isoformat(),
                    session_id=session_id
                )
                for msg in (all_session_messages or [])
            ]

            assigned_agent = metadata.get('assigned_agent')
            if not assigned_agent and 'agent_email' in session_row and session_row['agent_email']:
                assigned_agent = session_row['agent_email']
            if not assigned_agent and agent_id:
                assigned_agent = agent_id

            status = session_row.get('archive_status', 'active')
            if status == 'active':
                last_activity = session_row['last_activity_at']
                is_expired = False
                if last_activity:
                    if last_activity.tzinfo:
                        last_activity_naive = last_activity.replace(tzinfo=None) - (last_activity.utcoffset() or timedelta(0))
                    else:
                        last_activity_naive = last_activity
                    
                    time_diff = datetime.utcnow() - last_activity_naive
                    is_expired = time_diff.total_seconds() > 300 # 5 minutes

                if not (session_row['is_active'] and assigned_agent and not is_expired):
                    status = 'closed'

                if is_expired and session_row['is_active']:
                    await self.dao.archive_session(session_db_id, 'closed') # Effectively close in DB

            # Use cached feedback counts
            feedback_counts = batch_feedback_counts.get(session_id, {'positive_count': 0, 'negative_count': 0})
            session_feedback = None
            if feedback_counts['positive_count'] > 0 and feedback_counts['negative_count'] == 0:
                session_feedback = 'positive'
            elif feedback_counts['negative_count'] > 0:
                session_feedback = 'negative'

            # Get customer_name from metadata or generate it
            customer_name = metadata.get('customer_name')
            if not customer_name:
                customer_name = f"User-{session_db_id}"

            # Check if assigned to current user using numeric IDs only (not email)
            # Get agent_id directly from SQL join result — independent of email/metadata
            assigned_agent_id = session_row.get('agent_id')
            is_assigned_to_me = (assigned_agent_id is not None and current_user_id is not None and assigned_agent_id == current_user_id)

            from ..schemas.chat_log_schemas import ChatSessionResponse
            formatted_sessions.append(ChatSessionResponse(
                id=str(session_db_id),
                session_uuid=session_id,  # Include the UUID for frontend to use in mark-read/unread calls
                customer_name=customer_name,  # Use generated name if not in metadata
                customer_email=metadata.get('customer_email'),
                status=status,
                last_message_at=session_row['last_activity_at'].isoformat() if session_row['last_activity_at'] else datetime.utcnow().isoformat(),
                created_at=session_row['created_at'].isoformat() if session_row['created_at'] else None,
                assigned_agent=assigned_agent,
                assigned_agent_id=assigned_agent_id,  # Numeric ID for comparison (not masked)
                is_assigned_to_me=is_assigned_to_me,
                feedback=session_feedback,
                customer_feedback=session_feedback,
                agent_feedback=session_feedback,
                chat_type='human-handoff' if assigned_agent else 'ai-chat',
                is_session_read=session_row.get('is_session_read', False),
                messages=messages
            ))
        
        total_duration = time.time() - start_time
        logger.info(f"✅ [CHATLOG] Completed get_chat_sessions: {len(formatted_sessions)} sessions formatted in {total_duration:.2f}s total")
        return formatted_sessions, total_count

    async def get_session_messages(self, session_id: int):
        """Get all messages for a specific chat session (full conversation on click)."""
        return await self.dao.get_session_messages(session_id)

    async def update_session_feedback(self, session_id: int, feedback_type: str) -> bool:
        """Update session feedback (positive/negative)."""
        return await self.dao.update_session_feedback(session_id, feedback_type)

    async def send_agent_message(self, session_id: int, agent_email: str, text: str):
        """Send a message from an agent to a customer using numeric ID only.
        Broadcasting to customer SSE is handled by the router after this call."""
        message_id = await self.dao.create_message(session_id, 'agent', text)
        await self.dao.increment_message_count(session_id)
        return message_id

    async def send_customer_message(self, session_id: int, text: str):
        """Save a customer message to the database.
        Broadcasting is handled by the router after this call."""
        message_id = await self.dao.create_message(session_id, 'user', text)
        await self.dao.increment_message_count(session_id)
        return message_id


    async def update_chat_session(self, session_id: int, user_email: str, status: Optional[str] = None,
                                 assigned_agent: Optional[str] = None):
        """Update a chat session's metadata and status (numeric ID only)."""
        # session_id is already numeric (resolved by API Gateway)
        session_data = await self.dao.get_session_by_id_with_messages(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        # Get session UUID for cache clearing
        session_uuid = session_data.get('session_id')  # UUID format

        metadata = session_data['metadata'] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        if status is not None:
            metadata['status'] = status
            if status == 'closed':
                await self.dao.archive_session(session_id, 'closed')
                
                # Clear agent assignment cache (DB 4) when session closes
                from shared.redis_agent_cache import clear_assigned_agent
                await clear_assigned_agent(session_uuid)
                logger.info(f"Cleared agent assignment cache (DB 4) for session {session_uuid}")

        if assigned_agent is not None:
            if assigned_agent == '' or assigned_agent is None:
                if 'assigned_agent' in metadata:
                    del metadata['assigned_agent']
            else:
                metadata['assigned_agent'] = assigned_agent

        await self.dao.update_chat_session_metadata(session_id, metadata)

        # Broadcast session_ended event to customer when session is closed (REGARDLESS of who ended it)
        # Previously only sent if not assigned_agent, which meant:
        # - Agent closing session: NOT sent to customer ❌
        # - Customer closing session: sent to customer ✅
        # Now ALWAYS send to customer, regardless of assignment status
        if status == 'closed':
            if self.connection_manager:
                roles = await self.dao.check_user_role(user_email)
                ended_by = 'human agent' if (roles["is_admin"] or roles["is_agent"]) else 'customer'

                session_ended_message = {
                    "type": "session_ended",
                    "session_id": str(session_id),
                    "text": f"Session has been ended by the {ended_by}.",
                    "ended_by": ended_by,
                    "timestamp": datetime.utcnow().isoformat()
                }
                logger.info(f"📤 Broadcasting session_ended event to customer (session {session_id}, ended by {ended_by})")
                await self.connection_manager.broadcast_to_session(session_ended_message, str(session_id))
        return True

    async def end_customer_session(self, session_id: int, user_email: str):
        """End a chat session from the customer side (numeric ID only)."""
        # session_id is already numeric (resolved by API Gateway)
        # Verify session exists
        session = await self.dao.get_session_by_id_with_messages(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get session UUID for cache clearing
        session_uuid = session.get('session_id')  # UUID format

        await self.dao.archive_session(session_id, 'closed')
        
        # Clear agent assignment cache (DB 4) when session ends
        from shared.redis_agent_cache import clear_assigned_agent
        await clear_assigned_agent(session_uuid)
        logger.info(f"Cleared agent assignment cache (DB 4) for session {session_uuid}")

        if self.connection_manager:
            session_ended_message = {
                "type": "session_ended",
                "session_id": str(session_db_id),
                "text": "Session has been ended by the customer.",
                "ended_by": "customer",
                "timestamp": datetime.utcnow().isoformat()
            }
            await self.connection_manager.broadcast_to_session(session_ended_message, str(session_db_id))
        return True

    async def request_human_agent(self, session_id: int):
        """Request human agent connection - accepts numeric ID only (endpoint handles UUID conversion)"""
        logger.info(f"🧑 [HUMAN_AGENT] Request received for session {session_id}")

        # Step 1: Check if HIL is enabled
        hil_enabled = await self.dao.get_hil_enabled()
        logger.info(f"🔍 [HUMAN_AGENT] HIL enabled: {hil_enabled}")

        if not hil_enabled:
            logger.error(f"❌ [HUMAN_AGENT] HIL is disabled in configuration")
            raise HTTPException(status_code=503, detail="Human agent support is currently disabled")

        # Step 2: Assign chat with load balancing (keep as numeric ID, don't convert to string)
        logger.info(f"🔍 [HUMAN_AGENT] Starting load balancing for session {session_id}")
        assignment_result = await self.assign_chat_with_load_balancing(session_id)
        
        if not assignment_result:
            logger.error(f"❌ [HUMAN_AGENT] No available agents or admins to assign chat {session_id}")
            raise HTTPException(status_code=503, detail="No available agents or admins to assign chat")
        
        assigned_agent_email = assignment_result['email']
        assigned_agent_id = assignment_result['id']
        logger.info(f"✅ [HUMAN_AGENT] Successfully assigned session {session_id} to agent {assigned_agent_email} (ID: {assigned_agent_id})")
        return {'email': assigned_agent_email, 'id': assigned_agent_id}

    async def delete_session_messages(self, session_id: int) -> bool:
        """Delete all messages for a chat session using numeric ID only."""
        try:
            # session_id is already numeric (resolved by API Gateway)
            await self.dao.delete_messages_for_session(session_id)
            logger.info(f"Deleted all messages for session {session_db_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting messages for session {session_id}: {e}")
            raise

    async def delete_chat_session(self, session_id: int) -> bool:
        """Delete a chat session and its metadata using numeric ID only."""
        try:
            # session_id is already numeric (resolved by API Gateway)
            await self.dao.delete_chat_session_by_id(session_id)
            logger.info(f"Deleted chat session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting chat session {session_id}: {e}")
            raise

    async def mark_session_messages_as_unread(self, session_id: int) -> bool:
        """Mark all messages in a session as unread (delivered) using numeric ID only."""
        try:
            # session_id is already numeric (resolved by API Gateway)
            await self.dao.update_messages_status_for_session(session_id, 'delivered')
            logger.info(f"Marked all messages as unread for session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Error marking messages as unread for session {session_id}: {e}")
            raise

    async def mark_session_as_read(self, session_id: int, user_email: str) -> bool:
        """Mark entire session as read by human agent or admin (session-level)."""
        try:
            # Verify user is agent or admin
            roles = await self.dao.check_user_role(user_email)
            if not roles["is_agent"] and not roles["is_admin"]:
                logger.warning(f"User {user_email} is not a human agent or admin")
                raise HTTPException(status_code=403, detail="Only human agents and admins can mark sessions as read")

            # session_id is already numeric (resolved by API Gateway)
            logger.info(f"🔍 Marking session {session_id} as read by {user_email}")

            success = await self.dao.mark_session_as_read(session_id)
            if success:
                logger.info(f"✅ User {user_email} marked session {session_id} as read")
            else:
                logger.warning(f"❌ Failed to mark session {session_id} as read")
            return success
        except Exception as e:
            logger.error(f"Error marking session {session_id} as read: {e}")
            raise

    async def mark_session_as_unread(self, session_id: int, user_email: str) -> bool:
        """Mark entire session as unread by human agent or admin (session-level)."""
        try:
            # Verify user is agent or admin
            roles = await self.dao.check_user_role(user_email)
            if not roles["is_agent"] and not roles["is_admin"]:
                logger.warning(f"User {user_email} is not a human agent or admin")
                raise HTTPException(status_code=403, detail="Only human agents and admins can mark sessions as unread")

            # session_id is already numeric (resolved by API Gateway)
            success = await self.dao.mark_session_as_unread(session_id)
            if success:
                logger.info(f"✅ User {user_email} marked session {session_id} as unread")
            else:
                logger.warning(f"❌ Failed to mark session {session_id} as unread")
            return success
        except Exception as e:
            logger.error(f"Error marking session {session_id} as unread: {e}")
            raise

    async def get_unread_message_count(self, session_id: int) -> int:
        """Get count of unread messages in a session (numeric ID only)."""
        try:
            # session_id is already numeric (resolved by API Gateway)
            count = await self.dao.get_unread_messages_count(session_id)
            logger.info(f"Session {session_db_id} has {count} unread messages")
            return count
        except Exception as e:
            logger.error(f"Error getting unread message count for session {session_id}: {e}")
            return 0
