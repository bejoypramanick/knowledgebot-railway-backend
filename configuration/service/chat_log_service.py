import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from fastapi import HTTPException

from configuration.dao.chat_log_dao import ChatLogDAO
from configuration.dao.auth_dao import AuthDAO
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("chat_log_service", "configuration")

class ChatLogService:
    """Service layer for chat log operations"""
    
    def __init__(self):
        self.dao = ChatLogDAO()
        self.auth_dao = AuthDAO()
        self.connection_manager = None  # Placeholder - should be initialized if needed for websockets

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
            # Convert session_id to integer for DAO operations
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id
            logger.info(f"Chat session {session_db_id} assigned to agent {agent_email}")
            assignee_type = "agent"
            existing = await self.dao.get_session_assignment(session_db_id)
            if existing:
                await self.dao.update_session_assignment(session_db_id, agent_email, assignee_type, status='active')
            else:
                await self.dao.create_session_assignment(session_db_id, agent_email, assignee_type, status='active')
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
            agent_emails = await self.dao.get_all_human_agents()
            agent_loads = []
            
            if agent_emails:
                for email in agent_emails:
                    if await self.get_agent_online_status(email):
                        chat_count = await self.get_agent_chat_count(email)
                        agent_loads.append({'email': email, 'chat_count': chat_count})
            
            if not agent_loads:
                admin_emails = await self.dao.get_all_admins()
                for email in admin_emails:
                    if await self.get_agent_online_status(email):
                        chat_count = await self.get_agent_chat_count(email)
                        agent_loads.append({'email': email, 'chat_count': chat_count})
            
            if not agent_loads:
                return None
            
            agent_loads.sort(key=lambda x: x['chat_count'])
            assigned_agent = agent_loads[0]['email']
            await self.assign_chat_to_agent(session_id, assigned_agent)
            return assigned_agent
        except Exception as e:
            logger.error(f"Error in load balancing: {e}", exc_info=True)
            return None

    async def record_heartbeat(self, user_email: str):
        """Record heartbeat for an agent or admin."""
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_agent"] and not roles["is_admin"]:
            raise HTTPException(status_code=403, detail="User is not a human agent or admin")

        heartbeat_session_id = f"heartbeat_{user_email}"
        # Use UUID-based lookup for heartbeat sessions
        heartbeat_cs_id = await self.dao.get_session_db_id_by_uuid(heartbeat_session_id)
        if not heartbeat_cs_id:
            heartbeat_cs_id = await self.dao.create_chat_session(heartbeat_session_id, {})

        assignee_type = await self.dao.get_assignee_type(user_email)
        existing = await self.dao.get_session_assignment(heartbeat_cs_id)

        if existing:
            await self.dao.update_session_assignment(heartbeat_cs_id, user_email, assignee_type, status='active')
        else:
            await self.dao.create_session_assignment(heartbeat_cs_id, user_email, assignee_type, status='active')
        return True

    async def get_chat_sessions(self, role: str, user_email: str, archive_status: str, page: int, limit: int, agent_id: Optional[str] = None):
        """Get chat sessions with pagination, filtering, and efficiency."""
        offset = (page - 1) * limit
        
        if role == 'human_agent':
            await self.record_heartbeat(user_email)
            sessions_data = await self.dao.get_sessions_for_agent(user_email, archive_status, limit, offset)
            total_count = await self.dao.count_sessions_for_agent(user_email, archive_status)
        else:
            sessions_data = await self.dao.get_all_sessions(archive_status, limit, offset)
            total_count = await self.dao.count_all_sessions(archive_status)

        if not sessions_data:
            return [], total_count

        session_db_ids = [int(s['id']) if isinstance(s['id'], str) else s['id'] for s in sessions_data]
        logger.info(f"⚡ Fetching latest messages for {len(session_db_ids)} sessions (optimized)")

        # Fetch only LATEST message per session (optimized for list view)
        latest_messages = {}
        for session_id in session_db_ids:
            latest_msg = await self.dao.get_latest_message_for_session(session_id)
            if latest_msg:
                latest_messages[session_id] = latest_msg

        logger.info(f"📨 Loaded latest messages for {len(latest_messages)} sessions")

        # Get all session IDs for batch feedback query (uses session_id UUID)
        session_ids = [s['session_id'] for s in sessions_data]
        # OPTIMIZATION: Fetch feedback counts for all sessions in one query
        batch_feedback_counts = await self.dao.get_batch_feedback_counts(session_ids)

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
        
        return formatted_sessions, total_count

    async def get_session_messages(self, session_id: int | str):
        """Get all messages for a specific chat session (full conversation on click)."""
        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

        return await self.dao.get_session_messages(session_db_id)

    async def send_agent_message(self, session_id: int | str, agent_email: str, text: str):
        """Send a message from an agent to a customer using numeric ID only."""
        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

        message_id = await self.dao.create_message(session_db_id, 'agent', text)
        await self.dao.increment_message_count(session_db_id)

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

        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

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

        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

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
        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

        session_data = await self.dao.get_session_by_id_with_messages(session_db_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Chat session not found")

        metadata = session_data['metadata'] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)

        if status is not None:
            metadata['status'] = status
            if status == 'closed':
                await self.dao.archive_session(session_db_id, 'closed')

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
        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

        # Verify session exists
        session = await self.dao.get_session_by_id_with_messages(session_db_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        await self.dao.archive_session(session_db_id, 'closed')

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

    async def request_human_agent(self, session_id: int | str):
        """Request human agent connection using numeric ID only."""
        hil_enabled = await self.dao.get_hil_enabled()

        if not hil_enabled:
            raise HTTPException(status_code=503, detail="Human agent support is currently disabled")

        # Convert to int if string
        session_db_id = int(session_id) if isinstance(session_id, str) else session_id

        assigned_agent = await self.assign_chat_with_load_balancing(str(session_db_id))
        if not assigned_agent:
            raise HTTPException(status_code=503, detail="No available agents to assign chat")
        return assigned_agent

    async def delete_session_messages(self, session_id: int | str) -> bool:
        """Delete all messages for a chat session using numeric ID only."""
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            await self.dao.delete_messages_for_session(session_db_id)
            logger.info(f"Deleted all messages for session {session_db_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting messages for session {session_id}: {e}")
            raise

    async def delete_chat_session(self, session_id: int | str) -> bool:
        """Delete a chat session and its metadata using numeric ID only."""
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            await self.dao.delete_chat_session_by_id(session_db_id)
            logger.info(f"Deleted chat session {session_db_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting chat session {session_id}: {e}")
            raise

    async def mark_session_messages_as_unread(self, session_id: int | str) -> bool:
        """Mark all messages in a session as unread (delivered) using numeric ID only."""
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

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

            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id
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

            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

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
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            count = await self.dao.get_unread_messages_count(session_db_id)
            logger.info(f"Session {session_db_id} has {count} unread messages")
            return count
        except Exception as e:
            logger.error(f"Error getting unread message count for session {session_id}: {e}")
            return 0
