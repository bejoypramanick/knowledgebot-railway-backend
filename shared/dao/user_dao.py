from typing import Any, Dict, List, Optional

from shared.db import get_db_connection
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class UserDAO:
    """Shared DAO for user-related operations across all services."""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_user_roles(self, user_email: str) -> List[str]:
        """Get all roles for a user."""
        roles = []
        
        async with get_db_connection() as conn:
            # Check admin table
            admin_check = await conn.fetchrow(
                "SELECT id FROM admins WHERE email = $1 AND status = 'active'",
                user_email
            )
            if admin_check:
                roles.append("admin")
                logger.info(f"👑 Admin role confirmed for {user_email}")

            # Check human_agent table (no status column, check if not removed)
            agent_check = await conn.fetchrow(
                "SELECT id FROM human_agents WHERE email = $1 AND removed_at IS NULL",
                user_email
            )
            if agent_check:
                roles.append("human_agent")
                logger.info(f"🤖 Human agent role confirmed for {user_email}")

        return roles

    async def get_all_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    "SELECT email FROM human_agents WHERE removed_at IS NULL"
                )
                return [row['email'] for row in results]
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            return []

    async def get_all_admins(self) -> List[str]:
        """Get all admin emails."""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    "SELECT email FROM admins WHERE status = 'active'"
                )
                return [row['email'] for row in results]
        except Exception as e:
            logger.error(f"Error getting admins: {e}")
            return []

    async def check_admin_exists(self, email: str) -> bool:
        """Check if admin exists for given email."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    "SELECT 1 FROM admins WHERE email = $1",
                    email
                ) is not None
        except Exception as e:
            logger.error(f"Error checking admin existence: {e}")
            return False

    async def check_human_agent_exists(self, email: str) -> bool:
        """Check if human agent exists for given email."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    "SELECT 1 FROM human_agents WHERE email = $1 AND removed_at IS NULL",
                    email
                ) is not None
        except Exception as e:
            logger.error(f"Error checking human agent existence: {e}")
            return False

    async def is_admin(self, email: str) -> bool:
        """Check if user is admin."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    "SELECT 1 FROM admins WHERE email = $1",
                    email
                ) is not None
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            return False

    async def is_human_agent(self, email: str) -> bool:
        """Check if user is human agent."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    "SELECT 1 FROM human_agents WHERE email = $1 AND removed_at IS NULL",
                    email
                ) is not None
        except Exception as e:
            logger.error(f"Error checking human agent status: {e}")
            return False

    async def get_user_role_priority(self, email: str) -> Optional[str]:
        """Get user role with priority: admin > human_agent > user."""
        try:
            async with get_db_connection() as conn:
                # Check admin table
                admin_exists = await conn.fetchrow(
                    """
                    SELECT email, created_at
                    FROM admins
                    WHERE email = $1 AND status = 'active'
                    """,
                    email
                )

                if admin_exists:
                    return "admin"

                # Check human_agent table
                agent_exists = await conn.fetchrow(
                    """
                    SELECT email, created_at
                    FROM human_agents
                    WHERE email = $1 AND removed_at IS NULL
                    """,
                    email
                )

                if agent_exists:
                    return "human_agent"

                return "user"
        except Exception as e:
            logger.error(f"Error getting user role priority: {e}")
            return None
