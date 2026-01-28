import json
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from shared.logging_config import get_railway_logger

from ..dao.chat_log_dao import ChatLogDAO

logger = get_railway_logger(__name__)

class ChatLogService:
    def __init__(self, connection_manager=None):
        self.dao = ChatLogDAO()  # Service manages its own DAO
        self.connection_manager = connection_manager

    async def get_agent_online_status(self, agent_email: str) -> bool:
        """Check if an agent is online by checking their last activity timestamp."""
        try:
            return await self.dao.get_agent_online_status(agent_email)
        except Exception as e:
            logger.error(f"Error checking agent online status for {agent_email}: {e}")
            return False

    async def assign_chat_to_agent(self, session_id: str, agent_email: str) -> None:
        """Assign a chat session to a human agent and send notification."""
        try:
            session_db_id = await self.dao.get_session_db_id(session_id)
            
            metadata_dict = {"assigned_agent": agent_email, "status": "active"}
            if not session_db_id:
                session_db_id = await self.dao.create_chat_session(session_id, metadata_dict)
            else:
                await self.dao.update_chat_session_metadata(session_db_id, metadata_dict)
            
            assignee_type = await self.dao.get_assignee_type(agent_email)
            existing = await self.dao.get_session_assignment(session_db_id)
            
            if existing:
                await self.dao.update_session_assignment(session_db_id, agent_email, assignee_type)
            else:
                await self.dao.create_session_assignment(session_db_id, agent_email, assignee_type)
            
            await self.dao.update_last_activity(session_db_id)
            logger.info(f"Chat session {session_id} assigned to agent {agent_email}")
        except Exception as e:
            logger.error(f"Error assigning chat to agent: {e}", exc_info=True)
            raise

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

    async def get_online_agents(self, user_email: str):
        """Get all online human agents and admins with their active session counts."""
        try:
            # Use this service's DAO for role checking
            roles = await self.dao.check_user_role(user_email)
            if not roles["is_agent"] and not roles["is_admin"]:
                raise HTTPException(status_code=403, detail="Access denied")

            online_users = []
            agent_emails = await self.dao.get_all_human_agents()
            for email in agent_emails:
                if await self.get_agent_online_status(email):
                    chat_count = await self.get_agent_chat_count(email)
                    online_users.append({
                        "email": email, "role": "agent", "is_online": True, "active_sessions": chat_count
                    })

            admin_emails = await self.dao.get_all_admins()
            for email in admin_emails:
                if await self.get_agent_online_status(email):
                    chat_count = await self.get_agent_chat_count(email)
                    online_users.append({
                        "email": email, "role": "admin", "is_online": True, "active_sessions": chat_count
                    })

            return online_users
        except Exception as e:
            logger.error(f"Error getting online agents: {e}")
            raise

    async def record_heartbeat(self, user_email: str):
        """Record heartbeat for an agent or admin."""
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_agent"] and not roles["is_admin"]:
            raise HTTPException(status_code=403, detail="User is not a human agent or admin")
        
        heartbeat_session_id = f"heartbeat_{user_email}"
        heartbeat_cs_id = await self.dao.get_session_db_id(heartbeat_session_id)
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

        # Bulk fetch messages for all sessions
        session_db_ids = [s['id'] for s in sessions_data]
        messages_by_session = await self.dao.get_messages_for_sessions(session_db_ids)

        formatted_sessions = []
        for session_row in sessions_data:
            session_id = session_row['session_id']
            session_db_id = session_row['id']
            
            # Parse metadata
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

            # Prepare messages
            session_messages = messages_by_session.get(session_db_id, [])
            from ..schemas.chat_log_schemas import ChatMessageResponse
            messages = [
                ChatMessageResponse(
                    id=str(msg['id']),
                    text=msg['content'],
                    sender=msg['role'],
                    timestamp=msg['created_at'].isoformat() if msg['created_at'] else datetime.utcnow().isoformat(),
                    session_id=session_id
                ) for msg in session_messages
            ]

            # Determine assigned agent
            assigned_agent = metadata.get('assigned_agent')
            if not assigned_agent and 'agent_email' in session_row and session_row['agent_email']:
                assigned_agent = session_row['agent_email']
            if not assigned_agent and agent_id:
                assigned_agent = agent_id

            # Session expiry logic
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
                    await self.dao.archive_session(session_id, 'closed') # Effectively close in DB

            # Feedback logic (aggregated)
            # Fetch feedback for session_id (not session_db_id as per original code)
            feedback_result = await self.dao.conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                    COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
                FROM chat_feedback
                WHERE session_id = $1
                """,
                session_id
            )
            session_feedback = None
            if feedback_result:
                if feedback_result['positive_count'] > 0 and feedback_result['negative_count'] == 0:
                    session_feedback = 'positive'
                elif feedback_result['negative_count'] > 0:
                    session_feedback = 'negative'

            from ..schemas.chat_log_schemas import ChatSessionResponse
            formatted_sessions.append(ChatSessionResponse(
                id=session_id,
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
                messages=messages
            ))
        
        return formatted_sessions, total_count

    async def get_session_messages(self, session_id: str):
        """Get all messages for a specific chat session."""
        session_db_id = await self.dao.get_session_db_id(session_id)
        if not session_db_id:
            return []
        
        return await self.dao.get_messages(session_db_id)

    async def send_agent_message(self, session_id: str, agent_email: str, text: str):
        """Send a message from an agent to a customer."""
        session_db_id = await self.dao.get_session_db_id(session_id)
        if not session_db_id:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        message_id = await self.dao.create_message(session_db_id, 'agent', text)
        await self.dao.increment_message_count(session_db_id)
        
        if self.connection_manager:
            message_data = {
                "type": "agent_message",
                "message_id": message_id,
                "text": text,
                "sender": "agent",
                "session_id": session_id,
                "timestamp": datetime.utcnow().isoformat(),
                "agent_email": agent_email
            }
            await self.connection_manager.broadcast_to_session(message_data, session_id)
        
        return message_id

    async def archive_chat_session(self, session_id: str, archive_status: str, user_email: str):
        """Archive status of a chat session."""
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_admin"] and not roles["is_agent"]:
            raise HTTPException(status_code=403, detail="Only admins and human agents can archive sessions")

        success = await self.dao.archive_session(session_id, archive_status)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return True

    async def transfer_chat_session(self, session_id: str, user_email: str, target_agent_email: str):
        """Transfer a chat session to another agent."""
        roles = await self.dao.check_user_role(user_email)
        if not roles["is_agent"] and not roles["is_admin"]:
            raise HTTPException(status_code=403, detail="Access denied")
            
        target_roles = await self.dao.check_user_role(target_agent_email)
        if not target_roles["is_agent"] and not target_roles["is_admin"]:
            raise HTTPException(status_code=400, detail="Target user is not an agent or admin")
            
        # Use self.assign_chat_to_agent which is already implemented in this service
        await self.assign_chat_to_agent(session_id, target_agent_email)
        
        if self.connection_manager:
            transfer_message = {
                "type": "chat_transferred",
                "session_id": session_id,
                "transferred_to": target_agent_email,
                "transferred_by": user_email,
                "timestamp": datetime.utcnow().isoformat(),
                "text": "Chat has been transferred to another support agent"
            }
            await self.connection_manager.broadcast_to_session(transfer_message, session_id)
        
        session_db_id = await self.dao.get_session_db_id(session_id)
        if session_db_id:
            await self.dao.create_message(session_db_id, 'system', "Chat transferred to another support agent")
        
        return True

    async def update_chat_session(self, session_id: str, user_email: str, status: Optional[str] = None, 
                                 assigned_agent: Optional[str] = None, feedback: Optional[str] = None, 
                                 user_type: Optional[str] = None):
        """Update a chat session's metadata and status."""
        session_data = await self.dao.get_session_by_id_with_messages(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        session_db_id = session_data['id']
        metadata = session_data['metadata'] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        if status is not None:
            metadata['status'] = status
            if status == 'closed':
                await self.dao.archive_session(session_id, 'closed')
        
        if assigned_agent is not None:
            if assigned_agent == '' or assigned_agent is None:
                if 'assigned_agent' in metadata:
                    del metadata['assigned_agent']
            else:
                metadata['assigned_agent'] = assigned_agent
        
        if feedback is not None and user_type is not None:
            metadata[f"{user_type}_feedback"] = feedback
        
        await self.dao.update_chat_session_metadata(session_db_id, metadata)
        
        if status == 'closed' and not assigned_agent:
            if self.connection_manager:
                roles = await self.dao.check_user_role(user_email)
                ended_by = 'human agent' if (roles["is_admin"] or roles["is_agent"]) else 'customer'
                
                session_ended_message = {
                    "type": "session_ended",
                    "session_id": session_id,
                    "text": f"Session has been ended by the {ended_by}.",
                    "ended_by": ended_by,
                    "timestamp": datetime.utcnow().isoformat()
                }
                await self.connection_manager.broadcast_to_session(session_ended_message, session_id)
        
        return True

    async def end_customer_session(self, session_id: str, user_email: str):
        """End a chat session from the customer side."""
        session_db_id = await self.dao.get_session_db_id(session_id)
        if not session_db_id:
            raise HTTPException(status_code=404, detail="Session not found")

        await self.dao.archive_session(session_id, 'closed')

        if self.connection_manager:
            session_ended_message = {
                "type": "session_ended",
                "session_id": session_id,
                "text": "Session has been ended by the customer.",
                "ended_by": "customer",
                "timestamp": datetime.utcnow().isoformat()
            }
            await self.connection_manager.broadcast_to_session(session_ended_message, session_id)
        
        return True

    async def request_human_agent(self, session_id: str):
        """Request human agent connection."""
        config = await self.dao.conn.fetchrow("SELECT hil_enabled FROM configuration_metadata WHERE id = 1")
        hil_enabled = config['hil_enabled'] if config and config['hil_enabled'] is not None else True
        
        if not hil_enabled:
            raise HTTPException(status_code=503, detail="Human agent support is currently disabled")
        
        assigned_agent = await self.assign_chat_with_load_balancing(session_id)
        if not assigned_agent:
            raise HTTPException(status_code=503, detail="No available agents to assign chat")
        
        return assigned_agent

    async def public_end_customer_session(self, session_id: str):
        """Public endpoint to end customer session."""
        session_data = await self.dao.get_session_by_id_with_messages(session_id)
        if not session_data:
            raise HTTPException(status_code=404, detail="Chat session not found")
        
        session_db_id = session_data['id']
        metadata = session_data['metadata'] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        if 'assigned_agent' in metadata:
            del metadata['assigned_agent']
        
        await self.dao.update_chat_session_metadata(session_db_id, metadata)
        await self.dao.archive_session(session_id, 'closed')
        
        if self.connection_manager:
            session_ended_message = {
                'type': 'session_ended',
                'session_id': session_id,
                'ended_by': 'customer',
                'text': 'The session has ended by the customer.',
                'timestamp': time.time()
            }
            await self.connection_manager.broadcast_to_session(session_ended_message, session_id)
        
        return True
