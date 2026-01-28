import logging
import json
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

logger = logging.getLogger(__name__)

class ChatLogDAO:
    def __init__(self, connection):
        self.conn = connection

    async def get_agent_online_status(self, agent_email: str) -> bool:
        heartbeat_session_id = f"heartbeat_{agent_email}"
        heartbeat_activity = await self.conn.fetchval(
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
            return True
            
        recent_activity = await self.conn.fetchval(
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
        
        return recent_activity > 0

    async def get_session_db_id(self, session_id: str) -> Optional[int]:
         return await self.conn.fetchval("SELECT id FROM chat_sessions WHERE session_id = $1", session_id)

    async def create_chat_session(self, session_id: str, metadata: Dict[str, Any]) -> int:
        return await self.conn.fetchval(
            """
            INSERT INTO chat_sessions (session_id, is_active, metadata, last_activity_at, created_at)
            VALUES ($1, TRUE, $2::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            session_id, json.dumps(metadata)
        )

    async def update_chat_session_metadata(self, db_id: int, metadata: Dict[str, Any]):
        await self.conn.execute(
            """
            UPDATE chat_sessions 
            SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb,
                last_activity_at = COALESCE(last_activity_at, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $2
            """,
            json.dumps(metadata), db_id
        )

    async def get_assignee_type(self, email: str) -> str:
        return await self.conn.fetchval(
            """
            SELECT CASE 
                WHEN EXISTS (SELECT 1 FROM admins WHERE email = $1) 
                THEN 'admin'
                ELSE 'agent'
            END
            """,
            email
        )

    async def get_session_assignment(self, session_db_id: int) -> Optional[Dict[str, Any]]:
        return await self.conn.fetchrow("SELECT id FROM session_assignments WHERE session_id = $1", session_db_id)

    async def update_session_assignment(self, session_db_id: int, email: str, assignee_type: str, status: str = 'waiting'):
        await self.conn.execute(
            """
            UPDATE session_assignments
            SET assignee_email = $1, assignee_type = $2, status = $3, assigned_at = CURRENT_TIMESTAMP
            WHERE session_id = $4
            """,
            email, assignee_type, status, session_db_id
        )

    async def create_session_assignment(self, session_db_id: int, email: str, assignee_type: str, status: str = 'waiting'):
        await self.conn.execute(
            """
            INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status, assigned_at)
            VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
            """,
            session_db_id, email, assignee_type, status
        )

    async def update_last_activity(self, session_db_id: int):
        await self.conn.execute(
            """
            UPDATE chat_sessions 
            SET last_activity_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND (last_activity_at IS NULL OR last_activity_at < CURRENT_TIMESTAMP - INTERVAL '1 minute')
            """,
            session_db_id
        )

    async def get_agent_chat_count(self, agent_email: str) -> int:
        return await self.conn.fetchval(
            """
            SELECT COUNT(*) 
            FROM session_assignments 
            WHERE assignee_email = $1 AND status IN ('waiting', 'active')
            """,
            agent_email
        ) or 0

    async def get_all_human_agents(self) -> List[str]:
        rows = await self.conn.fetch("SELECT email FROM human_agents ORDER BY email")
        return [r['email'] for r in rows]

    async def get_all_admins(self) -> List[str]:
        rows = await self.conn.fetch("SELECT email FROM admins ORDER BY email")
        return [r['email'] for r in rows]

    async def check_user_role(self, email: str) -> Dict[str, bool]:
        is_agent = await self.conn.fetchval("SELECT COUNT(*) FROM human_agents WHERE email = $1", email)
        is_admin = await self.conn.fetchval("SELECT COUNT(*) FROM admins WHERE email = $1", email)
        return {"is_agent": bool(is_agent), "is_admin": bool(is_admin)}

    async def get_sessions_for_agent(self, agent_email: str, status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        return await self.conn.fetch(
            """
            SELECT DISTINCT
                cs.id, cs.session_id, cs.archive_status,
                COALESCE(cs.last_activity_at, cs.created_at, cs.updated_at, CURRENT_TIMESTAMP) as last_activity_at,
                cs.created_at, cs.metadata, cs.is_active
            FROM chat_sessions cs
            INNER JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE LOWER(sa.assignee_email) = LOWER($1)
            AND sa.status IN ('waiting', 'active')
            AND cs.archive_status = $2
            ORDER BY last_activity_at DESC
            LIMIT $3 OFFSET $4
            """,
            agent_email, status, limit, offset
        )

    async def count_sessions_for_agent(self, agent_email: str, status: str) -> int:
        return await self.conn.fetchval(
            """
            SELECT COUNT(DISTINCT cs.id)
            FROM chat_sessions cs
            INNER JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE LOWER(sa.assignee_email) = LOWER($1)
            AND sa.status IN ('waiting', 'active')
            AND cs.archive_status = $2
            """,
            agent_email, status
        ) or 0

    async def get_all_sessions(self, status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        return await self.conn.fetch(
            """
            SELECT 
                id, session_id, archive_status,
                COALESCE(last_activity_at, created_at, updated_at, CURRENT_TIMESTAMP) as last_activity_at,
                created_at, metadata, is_active
            FROM chat_sessions
            WHERE archive_status = $1
            ORDER BY last_activity_at DESC
            LIMIT $2 OFFSET $3
            """,
            status, limit, offset
        )

    async def count_all_sessions(self, status: str) -> int:
        return await self.conn.fetchval(
            "SELECT COUNT(*) FROM chat_sessions WHERE archive_status = $1",
            status
        ) or 0
        
    async def get_messages_for_sessions(self, session_ids: List[int]) -> List[Dict[str, Any]]:
        if not session_ids:
            return []
        return await self.conn.fetch(
            """
            SELECT id, session_id, message_text, sender_type, created_at
            FROM chat_messages
            WHERE session_id = ANY($1)
            ORDER BY created_at ASC
            """,
            session_ids
        )
        
    async def get_session_by_id_with_messages(self, session_id: str) -> Optional[Dict[str, Any]]:
        return await self.conn.fetchrow(
            """
            SELECT 
                cs.id, cs.session_id, cs.archive_status, cs.metadata, cs.is_active,
                cs.created_at, cs.last_activity_at,
                sa.assignee_email as assigned_agent
            FROM chat_sessions cs
            LEFT JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE cs.session_id = $1
            """,
            session_id
        )

    async def archive_session(self, session_id: str, archive_status: str) -> bool:
        """Archive or change the status of a chat session."""
        result = await self.conn.execute(
            """
            UPDATE chat_sessions
            SET archive_status = $1, updated_at = CURRENT_TIMESTAMP
            WHERE session_id = $2
            """,
            archive_status, session_id
        )
        return result != "UPDATE 0"

    async def get_messages(self, session_db_id: int) -> List[Dict[str, Any]]:
        """Get all messages for a specific chat session."""
        return await self.conn.fetch(
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

    async def create_message(self, session_db_id: int, role: str, content: str) -> str:
        """Insert a new message into the chat_messages table."""
        return await self.conn.fetchval(
            """
            INSERT INTO chat_messages (session_id, role, content)
            VALUES ($1, $2, $3)
            RETURNING id::text
            """,
            session_db_id, role, content
        )

    async def increment_message_count(self, session_db_id: int) -> None:
        """Increment the message count for a session and update last activity."""
        await self.conn.execute(
            """
            UPDATE chat_sessions 
            SET last_activity_at = CURRENT_TIMESTAMP,
                message_count = message_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            session_db_id
        )
