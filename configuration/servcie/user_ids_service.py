"""
User IDs Service Layer
Provides business logic for user ID management operations
"""
import logging
import uuid
from typing import List, Optional, Dict, Any
from ..dao.user_dao import UserDAO

logger = logging.getLogger(__name__)

class UserIdsService:
    """Service layer for user ID management"""
    
    def __init__(self, user_dao: UserDAO):
        self.user_dao = user_dao
    
    async def get_or_create_user_id(self, email: Optional[str] = None, role: str = 'customer') -> Dict[str, Any]:
        """Get existing user ID or create new one"""
        try:
            if email:
                # Try to find existing user
                user_id = await self.user_dao.get_user_id_by_email(email)
                if user_id:
                    return {"user_id": user_id, "email": email, "role": role}
            
            # Create new user ID
            new_user_id = str(uuid.uuid4())
            await self.user_dao.create_user(new_user_id, email, role)
            
            return {"user_id": new_user_id, "email": email, "role": role}
        except Exception as e:
            logger.error(f"Error getting/creating user ID: {e}")
            raise
    
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        try:
            return await self.user_dao.get_user_by_id(user_id)
        except Exception as e:
            logger.error(f"Error getting user by ID: {e}")
            raise
