from typing import Any, Dict, List, Optional

from shared.db import get_db_connection
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class AuthDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_admin(self, email: str, token: str, created_by_email: str) -> str:
        """Create a new admin with pending status."""
        async with get_db_connection() as conn:
            return await conn.fetchval(
                """
                INSERT INTO admins (email, status, confirmation_token, created_by_email)
                VALUES ($1, 'active', $2, $3)
                RETURNING id::text
                """,
                email, token, created_by_email
            )

    async def remove_admin(self, email: str) -> None:
        """Remove an admin by setting status to removed."""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                UPDATE admins 
                SET status = 'removed',
                    removed_at = NOW()
                WHERE email = $1
                """,
                email
            )

    async def list_all_admins(self) -> List[Dict[str, Any]]:
        """List all admins."""
        async with get_db_connection() as conn:
            return await conn.fetch(
                """
                SELECT email, created_at, created_by_email
                FROM admins
                ORDER BY created_at DESC
                """
            )

    async def create_human_agent(self, email: str) -> str:
        """Create a new human agent."""
        async with get_db_connection() as conn:
            return await conn.fetchval(
                """
                INSERT INTO human_agents (email)
                VALUES ($1)
                RETURNING id::text
                """,
                email
            )

    async def remove_human_agent(self, email: str) -> None:
        """Remove a human agent by setting status to removed."""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                UPDATE human_agents 
                SET status = 'removed',
                    removed_at = NOW()
                WHERE email = $1
                """,
                email
            )

    async def remove_human_agent(self, email: str) -> None:
        """Remove a human agent by setting status to removed."""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                UPDATE human_agents 
                SET status = 'removed',
                    removed_at = NOW()
                WHERE email = $1
                """,
                email
            )

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get available human agents for assignment."""
        async with get_db_connection() as conn:
            return await conn.fetch(
                """
                SELECT email FROM human_agents 
                WHERE status = 'active'
                ORDER BY created_at DESC
                """
            )

    async def get_agent_by_id(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get human agent by ID."""
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                "SELECT * FROM human_agents WHERE id = $1",
                agent_id
            )

    async def create_agent_assignment(self, session_id: str, agent_id: str, assigned_by: str) -> None:
        """Create an agent session assignment."""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO agent_session_assignments 
                (session_id, agent_id, status, assigned_at, assigned_by)
                VALUES ($1, $2, 'assigned', NOW(), $3)
                """,
                session_id, agent_id, assigned_by
            )

    async def get_existing_assignment(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get existing agent assignment for a session."""
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                """
                SELECT ha.* FROM human_agents ha
                JOIN agent_session_assignments asa ON ha.id = asa.agent_id
                WHERE asa.session_id = $1 AND asa.status = 'active'
                """,
                session_id
            )

    async def execute_role_query(self, query: str, email: str) -> List[Dict[str, Any]]:
        """Execute role query."""
        async with get_db_connection() as conn:
            return await conn.fetch(query, email)
