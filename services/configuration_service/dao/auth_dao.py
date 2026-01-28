import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class AuthDAO:
    def __init__(self, connection):
        self.conn = connection

    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        return await self.conn.fetchrow(
            "SELECT email FROM admins WHERE email = $1",
            email
        )

    async def check_human_agent_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if human agent exists for given email."""
        return await self.conn.fetchrow(
            "SELECT email FROM human_agents WHERE email = $1",
            email
        )
