"""
Auth Service Layer
Provides business logic for authentication operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.auth_dao import AuthDAO
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class AuthService:
    """Service layer for authentication"""
    
    @classmethod
    async def add_admin(cls, email: str) -> bool:
        """Add admin user"""
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            try:
                await auth_dao.add_admin(email)
                logger.info(f"Admin added: {email}")
                return True
            except Exception as e:
                logger.error(f"Error adding admin: {e}")
                raise
    
    @classmethod
    async def add_human_agent(cls, email: str) -> bool:
        """Add human agent"""
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            try:
                await auth_dao.add_human_agent(email)
                logger.info(f"Human agent added: {email}")
                return True
            except Exception as e:
                logger.error(f"Error adding human agent: {e}")
                raise
    
    @classmethod
    async def get_admins(cls) -> List[Dict[str, Any]]:
        """Get all admins"""
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            try:
                return await auth_dao.get_admins()
            except Exception as e:
                logger.error(f"Error fetching admins: {e}")
                raise
    
    @classmethod
    async def get_human_agents(cls) -> List[Dict[str, Any]]:
        """Get all human agents"""
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            try:
                return await auth_dao.get_human_agents()
            except Exception as e:
                logger.error(f"Error fetching human agents: {e}")
                raise
