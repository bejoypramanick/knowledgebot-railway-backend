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

    async def _resolve_session_db_id(self, session_id: int | str) -> Optional[int]:
        """
        Resolve session_id (UUID or int) to database ID.
        Tries Redis cache first, then falls back to DB query.
        Returns None if session not found.
        """
        # If already numeric, return as-is
        if isinstance(session_id, int):
            return session_id

        # Try Redis cache first
        from shared.redis_pubsub_manager import get_pubsub_redis
        try:
            redis_client = await get_pubsub_redis()
            cache_key = f"session:{session_id}:db_id"
            cached_id = await redis_client.get(cache_key)
            if cached_id:
                return int(cached_id)
        except Exception as e:
            logger.warning(f"Redis cache lookup failed for {session_id}: {e}, falling back to DB")

        # Fall back to DB lookup
        session_db_id = await self.dao.get_session_db_id_by_uuid(session_id)

        # Cache the result if found
        if session_db_id:
            try:
                redis_client = await get_pubsub_redis()
                cache_key = f"session:{session_id}:db_id"
                await redis_client.setex(cache_key, 3600, str(session_db_id))  # 1 hour TTL
            except Exception as e:
                logger.warning(f"Failed to cache session ID mapping: {e}")

        return session_db_id

    async def get_all_chat_logs(self) -> List[Dict[str, Any]]:
        """Get all chat logs"""
        try:
            return await self.dao.get_all_chat_logs()
        except Exception as e:
            logger.error(f"Error getting all chat logs: {e}")
            raise

    async def delete_chat_log(self, session_id: str, user_email: str) -> Dict[str, Any]:
        """Delete a chat log"""
        try:
            return await self.dao.delete_chat_log(session_id)
        except Exception as e:
            logger.error(f"Error deleting chat log {session_id}: {e}")
            raise

    async def assign_chat_to_agent(self, session_id: str, agent_email: str):
        """Assign chat to specific agent"""
        try:
            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                logger.error(f"❌ Cannot assign chat: session {session_id} does not exist")
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

            # Validate that session exists before creating assignment
            session = await self.dao.get_session_by_id_with_messages(session_db_id)
            if not session:
                logger.error(f"❌ Cannot assign chat: session {session_db_id} does not exist")
                raise HTTPException(status_code=404, detail=f"Session {session_db_id} not found")
            
            # Get session UUID for caching and broadcasting
            session_uuid = session.get('session_id')  # UUID format
            
            logger.info(f"Chat session {session_db_id} assigned to agent {agent_email}")
            assignee_type = "agent"
            existing = await self.dao.get_session_assignment(session_db_id)
            if existing:
                await self.dao.update_session_assignment(session_db_id, agent_email, assignee_type, status='active')
            else:
                await self.dao.create_session_assignment(session_db_id, agent_email, assignee_type, status='active')
            
            # Cache the agent assignment in Redis (TTL: 1 hour)
            # This avoids querying session_assignments table on every message
            from shared.redis_pubsub_manager import get_pubsub_redis, broadcast_event_to_session
            redis_client = await get_pubsub_redis()
            agent_cache_key = f"session:assigned_agent:{session_uuid}"
            await redis_client.set(agent_cache_key, agent_email, ex=3600)
            logger.info(f"💾 Cached agent assignment: {session_uuid} → {agent_email} (TTL: 1h)")
            
            # CRITICAL: Broadcast to BOTH agent AND customer
            assignment_event = {
                "type": "chat_assigned",
                "session_id": str(session_db_id),
                "agent_email": agent_email,
                "assignee_type": assignee_type,
                "status": "active",
                "message": "New chat assigned to you",
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Send to agent (so it appears in their ChatLog)
            await broadcast_event_to_agent(agent_email, assignment_event)
            logger.info(f"📤 Sent assignment notification to agent {agent_email} via Redis Pub/Sub")
            
            # Send to customer (so UI blocks AI and enables agent chat)
            # CRITICAL: Use session UUID, not numeric ID
            await broadcast_event_to_session(session_uuid, assignment_event)
            logger.info(f"📤 Sent assignment notification to customer session {session_uuid} via Redis Pub/Sub")
            
        except Exception as e:
            logger.error(f"Error assigning chat to agent: {e}", exc_info=True)
            raise

    async def get_agent_online_status(self, email: str) -> bool:
        """Check if agent is online"""
        return True 

    async def get_agent_chat_count(self, agent_email: str) -> int:
        """Get the number of active chats assigned to an agent."""
        try:
            return await self.dao.get_agent_chat_count(agent_email)
        except Exception as e:
            logger.error(f"Error getting agent chat count: {e}")
            return 0

    async def assign_chat_with_load_balancing(self, session_id: str) -> Optional[str]:
        """Assign a chat to an available agent using load balancing."""
        try:
            logger.info(f"🔍 [LOAD_BALANCE] Starting load balancing for session {session_id}")
            
            # Step 1: Get all human agents
            agent_emails = await self.dao.get_all_human_agents()
            logger.info(f"🔍 [LOAD_BALANCE] Found {len(agent_emails)} human agents: {agent_emails}")
            
            agent_loads = []
            
            if agent_emails:
                logger.info(f"🔍 [LOAD_BALANCE] Checking availability of {len(agent_emails)} human agents")
                for email in agent_emails:
                    is_online = await self.get_agent_online_status(email)
                    logger.info(f"🔍 [LOAD_BALANCE] Agent {email} online status: {is_online}")
                    
                    if is_online:
                        chat_count = await self.get_agent_chat_count(email)
                        logger.info(f"🔍 [LOAD_BALANCE] Agent {email} has {chat_count} active chats")
                        agent_loads.append({'email': email, 'chat_count': chat_count})
            else:
                logger.warning(f"⚠️ [LOAD_BALANCE] No human agents found in database")
            
            # Step 2: If no human agents, try admins
            if not agent_loads:
                logger.info(f"🔍 [LOAD_BALANCE] No available human agents, checking admins")
                admin_emails = await self.dao.get_all_admins()
                logger.info(f"🔍 [LOAD_BALANCE] Found {len(admin_emails)} admins: {admin_emails}")
                
                for email in admin_emails:
                    is_online = await self.get_agent_online_status(email)
                    logger.info(f"🔍 [LOAD_BALANCE] Admin {email} online status: {is_online}")
                    
                    if is_online:
                        chat_count = await self.get_agent_chat_count(email)
                        logger.info(f"🔍 [LOAD_BALANCE] Admin {email} has {chat_count} active chats")
                        agent_loads.append({'email': email, 'chat_count': chat_count})
            
            # Step 3: Check if we found any agents
            if not agent_loads:
                logger.error(f"❌ [LOAD_BALANCE] No available agents or admins found for session {session_id}")
                logger.error(f"❌ [LOAD_BALANCE] Human agents in DB: {agent_emails}")
                logger.error(f"❌ [LOAD_BALANCE] Admins in DB: {admin_emails if 'admin_emails' in locals() else 'Not checked'}")
                return None
            
            # Step 4: Sort by chat count and assign to least busy agent
            agent_loads.sort(key=lambda x: x['chat_count'])
            assigned_agent = agent_loads[0]['email']
            logger.info(f"✅ [LOAD_BALANCE] Selected agent {assigned_agent} with {agent_loads[0]['chat_count']} chats")
            logger.info(f"🔍 [LOAD_BALANCE] All available agents: {agent_loads}")
            
            # Step 5: Assign the chat
            await self.assign_chat_to_agent(session_id, assigned_agent)
            logger.info(f"✅ [LOAD_BALANCE] Successfully assigned session {session_id} to {assigned_agent}")
            
            return assigned_agent
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

            # Only include latest message in list view (full conversation loaded on click)
            from ..schemas.chat_log_schemas import ChatMessageResponse
            latest_msg = latest_messages.get(session_db_id)
            messages = []
            if latest_msg:
                messages = [
                    ChatMessageResponse(
                        id=str(latest_msg['id']),
                        text=latest_msg['content'],
                        sender=latest_msg['role'],
                        timestamp=latest_msg['created_at'].isoformat() if latest_msg['created_at'] else datetime.utcnow().isoformat(),
                        session_id=session_id
                    )
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

            from ..schemas.chat_log_schemas import ChatSessionResponse
            formatted_sessions.append(ChatSessionResponse(
                id=str(session_db_id),
                customer_name=metadata.get('customer_name'),
                customer_email=metadata.get('customer_email'),
                status=status,
                last_message_at=session_row['last_activity_at'].isoformat() if session_row['last_activity_at'] else datetime.utcnow().isoformat(),
                created_at=session_row['created_at'].isoformat() if session_row['created_at'] else None,
                assigned_agent=assigned_agent,
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

    async def send_agent_message(self, session_id: int, agent_email: str, text: str):
        """Send a message from an agent to a customer using numeric ID only."""
        message_id = await self.dao.create_message(session_id, 'agent', text)
        await self.dao.increment_message_count(session_id)

        if self.connection_manager:
            message_data = {
                "type": "agent_message",
                "message_id": message_id,
                "text": text,
                "sender": "agent",
                "session_id": str(session_db_id),
                "timestamp": datetime.utcnow().isoformat(),
                "agent_email": agent_email
            }
            await self.connection_manager.broadcast_to_session(message_data, str(session_db_id))

        return message_id

    async def archive_chat_session(self, session_id: int | str, archive_status: str, user_email: str):
        """Archive status of a chat session using numeric ID only."""
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_admin"] and not roles["is_agent"]:
            raise HTTPException(status_code=403, detail="Only admins and human agents can archive sessions")

        # Resolve session_id using cache and DB
        session_db_id = await self._resolve_session_db_id(session_id)
        if not session_db_id:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        success = await self.dao.archive_session(session_db_id, archive_status)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return True

    async def transfer_chat_session(self, session_id: int | str, user_email: str, target_agent_email: str):
        """Transfer a chat session to another agent using numeric ID only."""
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_agent"] and not roles["is_admin"]:
            raise HTTPException(status_code=403, detail="Access denied")

        target_roles = await self.dao.check_user_role(target_agent_email)
        if not target_roles["is_agent"] and not target_roles["is_admin"]:
            raise HTTPException(status_code=400, detail="Target user is not an agent or admin")

        # Resolve session_id using cache and DB
        session_db_id = await self._resolve_session_db_id(session_id)
        if not session_db_id:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        await self.assign_chat_to_agent(str(session_db_id), target_agent_email)

        if self.connection_manager:
            transfer_message = {
                "type": "chat_transferred",
                "session_id": str(session_db_id),
                "transferred_to": target_agent_email,
                "transferred_by": user_email,
                "timestamp": datetime.utcnow().isoformat(),
                "text": "Chat has been transferred to another support agent"
            }
            await self.connection_manager.broadcast_to_session(transfer_message, str(session_db_id))

        await self.dao.create_message(session_db_id, 'system', "Chat transferred to another support agent")
        return True

    async def update_chat_session(self, session_id: int | str, user_email: str, status: Optional[str] = None,
                                 assigned_agent: Optional[str] = None):
        """Update a chat session's metadata and status using numeric ID only."""
        # Resolve session_id using cache and DB
        session_db_id = await self._resolve_session_db_id(session_id)
        if not session_db_id:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        session_data = await self.dao.get_session_by_id_with_messages(session_db_id)
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
                await self.dao.archive_session(session_db_id, 'closed')
                
                # Clear agent assignment cache when session closes
                from shared.redis_pubsub_manager import get_pubsub_redis
                redis_client = await get_pubsub_redis()
                agent_cache_key = f"session:assigned_agent:{session_uuid}"
                await redis_client.delete(agent_cache_key)
                logger.info(f"🗑️ Cleared agent assignment cache for session {session_uuid}")

        if assigned_agent is not None:
            if assigned_agent == '' or assigned_agent is None:
                if 'assigned_agent' in metadata:
                    del metadata['assigned_agent']
            else:
                metadata['assigned_agent'] = assigned_agent

        await self.dao.update_chat_session_metadata(session_db_id, metadata)

        if status == 'closed' and not assigned_agent:
            if self.connection_manager:
                roles = await self.dao.check_user_role(user_email)
                ended_by = 'human agent' if (roles["is_admin"] or roles["is_agent"]) else 'customer'

                session_ended_message = {
                    "type": "session_ended",
                    "session_id": str(session_db_id),
                    "text": f"Session has been ended by the {ended_by}.",
                    "ended_by": ended_by,
                    "timestamp": datetime.utcnow().isoformat()
                }
                await self.connection_manager.broadcast_to_session(session_ended_message, str(session_db_id))
        return True

    async def end_customer_session(self, session_id: int | str, user_email: str):
        """End a chat session from the customer side."""
        # Resolve session_id using cache and DB
        session_db_id = await self._resolve_session_db_id(session_id)
        if not session_db_id:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        # Verify session exists
        session = await self.dao.get_session_by_id_with_messages(session_db_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Get session UUID for cache clearing
        session_uuid = session.get('session_id')  # UUID format

        await self.dao.archive_session(session_db_id, 'closed')
        
        # Clear agent assignment cache when session ends
        from shared.redis_pubsub_manager import get_pubsub_redis
        redis_client = await get_pubsub_redis()
        agent_cache_key = f"session:assigned_agent:{session_uuid}"
        await redis_client.delete(agent_cache_key)
        logger.info(f"🗑️ Cleared agent assignment cache for session {session_uuid}")

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

        # Step 2: Assign chat with load balancing
        logger.info(f"🔍 [HUMAN_AGENT] Starting load balancing for session {session_id}")
        assigned_agent = await self.assign_chat_with_load_balancing(str(session_id))
        
        if not assigned_agent:
            logger.error(f"❌ [HUMAN_AGENT] No available agents or admins to assign chat {session_id}")
            raise HTTPException(status_code=503, detail="No available agents or admins to assign chat")
        
        logger.info(f"✅ [HUMAN_AGENT] Successfully assigned session {session_id} to agent {assigned_agent}")
        return assigned_agent

    async def delete_session_messages(self, session_id: int | str) -> bool:
        """Delete all messages for a chat session using numeric ID only."""
        try:
            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

            await self.dao.delete_messages_for_session(session_db_id)
            logger.info(f"Deleted all messages for session {session_db_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting messages for session {session_id}: {e}")
            raise

    async def delete_chat_session(self, session_id: int | str) -> bool:
        """Delete a chat session and its metadata using numeric ID only."""
        try:
            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

            await self.dao.delete_chat_session_by_id(session_db_id)
            logger.info(f"Deleted chat session {session_db_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting chat session {session_id}: {e}")
            raise

    async def mark_session_messages_as_unread(self, session_id: int | str) -> bool:
        """Mark all messages in a session as unread (delivered) using numeric ID only."""
        try:
            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

            await self.dao.update_messages_status_for_session(session_db_id, 'delivered')
            logger.info(f"Marked all messages as unread for session {session_db_id}")
            return True
        except Exception as e:
            logger.error(f"Error marking messages as unread for session {session_id}: {e}")
            raise

    async def mark_session_as_read(self, session_id: int | str, user_email: str) -> bool:
        """Mark entire session as read by human agent or admin (session-level)."""
        try:
            # Verify user is agent or admin
            roles = await self.dao.check_user_role(user_email)
            if not roles["is_agent"] and not roles["is_admin"]:
                logger.warning(f"User {user_email} is not a human agent or admin")
                raise HTTPException(status_code=403, detail="Only human agents and admins can mark sessions as read")

            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
            logger.info(f"🔍 Marking session {session_db_id} as read by {user_email}")

            success = await self.dao.mark_session_as_read(session_db_id)
            if success:
                logger.info(f"✅ User {user_email} marked session {session_db_id} as read")
            else:
                logger.warning(f"❌ Failed to mark session {session_db_id} as read")
            return success
        except Exception as e:
            logger.error(f"Error marking session {session_id} as read: {e}")
            raise

    async def mark_session_as_unread(self, session_id: int | str, user_email: str) -> bool:
        """Mark entire session as unread by human agent or admin (session-level)."""
        try:
            # Verify user is agent or admin
            roles = await self.dao.check_user_role(user_email)
            if not roles["is_agent"] and not roles["is_admin"]:
                logger.warning(f"User {user_email} is not a human agent or admin")
                raise HTTPException(status_code=403, detail="Only human agents and admins can mark sessions as unread")

            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

            success = await self.dao.mark_session_as_unread(session_db_id)
            if success:
                logger.info(f"✅ User {user_email} marked session {session_db_id} as unread")
            else:
                logger.warning(f"❌ Failed to mark session {session_db_id} as unread")
            return success
        except Exception as e:
            logger.error(f"Error marking session {session_id} as unread: {e}")
            raise

    async def get_unread_message_count(self, session_id: int | str) -> int:
        """Get count of unread messages in a session using numeric ID only."""
        try:
            # Resolve session_id using cache and DB
            session_db_id = await self._resolve_session_db_id(session_id)
            if not session_db_id:
                raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

            count = await self.dao.get_unread_messages_count(session_db_id)
            logger.info(f"Session {session_db_id} has {count} unread messages")
            return count
        except Exception as e:
            logger.error(f"Error getting unread message count for session {session_id}: {e}")
            return 0
