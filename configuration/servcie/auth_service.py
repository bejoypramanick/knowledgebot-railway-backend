"""
Auth Service Layer
Provides business logic for authentication operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.auth_dao import AuthDAO

logger = logging.getLogger(__name__)

class AuthService:
    """Service layer for authentication"""
    
    def __init__(self):
        self.auth_dao = AuthDAO()  # Service manages its own DAO
    
    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        try:
            return await self.auth_dao.check_admin_exists(email)
        except Exception as e:
            logger.error(f"Error checking admin exists: {e}")
            raise
    
    async def check_human_agent_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if human agent exists for given email."""
        try:
            return await self.auth_dao.check_human_agent_exists(email)
        except Exception as e:
            logger.error(f"Error checking human agent exists: {e}")
            raise
    
    async def execute_role_query(self, query: str, email: str) -> List[Dict[str, Any]]:
        """Execute role query."""
        try:
            return await self.auth_dao.execute_role_query(query, email)
        except Exception as e:
            logger.error(f"Error executing role query: {e}")
            raise
    
    async def add_admin(self, email: str) -> bool:
        """Add admin user"""
        try:
            await self.auth_dao.add_admin(email)
            logger.info(f"Admin added: {email}")
            return True
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            raise
    
    async def add_human_agent(self, email: str) -> bool:
        """Add human agent"""
        try:
            await self.auth_dao.add_human_agent(email)
            logger.info(f"Human agent added: {email}")
            return True
        except Exception as e:
            logger.error(f"Error adding human agent: {e}")
            raise
    
    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all admins"""
        try:
            return await self.auth_dao.get_admins()
        except Exception as e:
            logger.error(f"Error fetching admins: {e}")
            raise
    
    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        try:
            return await self.auth_dao.get_human_agents()
        except Exception as e:
            logger.error(f"Error fetching human agents: {e}")
            raise
