import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class UserDAO:
    def __init__(self, connection):
        self.conn = connection

    async def get_unique_id_by_email_role(self, email: str, role: str) -> Optional[Dict[str, Any]]:
        """Get unique ID by email and role."""
        return await self.conn.fetchrow(
            """
            SELECT unique_id, created_at 
            FROM user_unique_ids 
            WHERE email = $1 AND role = $2
            """,
            email, role
        )

    async def check_unique_id_exists(self, unique_id: str) -> Optional[str]:
        """Check if unique ID already exists."""
        return await self.conn.fetchval(
            "SELECT unique_id FROM user_unique_ids WHERE unique_id = $1",
            unique_id
        )

    async def create_unique_id(self, email: str, unique_id: str, role: str) -> None:
        """Create a new unique ID."""
        await self.conn.execute(
            """
            INSERT INTO user_unique_ids (email, unique_id, role)
            VALUES ($1, $2, $3)
            """,
            email, unique_id, role
        )

    async def get_unique_id_by_uid(self, unique_id: str) -> Optional[Dict[str, Any]]:
        """Get unique ID details by UID."""
        return await self.conn.fetchrow(
            """
            SELECT unique_id, role, created_at
            FROM user_unique_ids 
            WHERE unique_id = $1
            """,
            unique_id
        )

    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        return await self.conn.fetchrow(
            """
            SELECT email, created_at
            FROM admins
            WHERE email = $1
            """,
            email
        )

    async def check_human_agent_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if human agent exists for given email."""
        return await self.conn.fetchrow(
            """
            SELECT email, created_at
            FROM human_agents
            WHERE email = $1
            """,
            email
        )

    async def get_user_role_priority(self, email: str) -> Optional[str]:
        """Get user role with priority: admin > human_agent > user."""
        # Check admin table
        admin_exists = await self.conn.fetchrow(
            """
            SELECT email, created_at
            FROM admins
            WHERE email = $1
            """,
            email
        )

        if admin_exists:
            return "admin"

        # Check human_agent table
        agent_exists = await self.conn.fetchrow(
            """
            SELECT email, created_at
            FROM human_agents
            WHERE email = $1
            """,
            email
        )

        if agent_exists:
            return "human_agent"

        return "user"

    async def is_admin(self, email: str) -> bool:
        """Check if user is admin."""
        return await self.conn.fetchval(
            "SELECT 1 FROM admins WHERE email = $1",
            email
        ) is not None

    async def is_human_agent(self, email: str) -> bool:
        """Check if user is human agent."""
        return await self.conn.fetchval(
            "SELECT 1 FROM human_agents WHERE email = $1",
            email
        ) is not None

    async def get_user_roles(self, user_email: str) -> List[str]:
        """Get all roles for a user."""
        roles = []

        # Check admin table
        admin_check = await self.conn.fetchrow(
            "SELECT id FROM admins WHERE email = $1",
            user_email
        )
        if admin_check:
            roles.append("admin")
            logger.info(f"👑 Admin role confirmed for {user_email}")

        # Check human_agent table
        agent_check = await self.conn.fetchrow(
            "SELECT id FROM human_agents WHERE email = $1",
            user_email
        )
        if agent_check:
            roles.append("human_agent")
            logger.info(f"🤖 Human agent role confirmed for {user_email}")

        return roles
