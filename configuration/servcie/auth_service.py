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
    
    def __init__(self, auth_dao: AuthDAO):
        self.auth_dao = auth_dao
    
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
