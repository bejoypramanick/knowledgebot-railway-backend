"""
Auth Service Layer
Provides business logic for authentication operations
"""
from typing import Any, Dict, List, Optional
from fastapi import HTTPException

from shared.otel_logger import get_otel_logger

from ..dao.auth_dao import AuthDAO

logger = get_otel_logger("auth_service", "configuration")

class AuthService:
    """Service layer for authentication"""
    
    def __init__(self):
        self.auth_dao = AuthDAO()  # Service manages its own DAO
    
    
    async def get_user_role(self, email: str) -> dict:
        """Get user role (admin, human_agent, or user) for a given email"""
        try:
            # Get all roles for the user in a single database call
            user_roles_data = await self.auth_dao.get_user_roles(email)
            
            # Extract role names from the results
            roles = [role_data['role_name'] for role_data in user_roles_data]
            
            # Return all roles or default to user
            if not roles:
                roles = ["user"]
            
            return {"email": email, "roles": roles}
        except Exception as e:
            logger.error(f"Error getting user role: {e}")
            raise

    async def remove_admin(self, email: str, current_user_email: str) -> dict:
        """Remove an admin. Only admins can remove other admins."""
        # Check if current user is an admin
        current_user_roles = await self.get_user_role(current_user_email)
        
        if 'admin' not in current_user_roles['roles']:
            raise HTTPException(status_code=403, detail="Only admins can remove other admins")
        
        # Check if user has admin role
        user_roles = await self.get_user_role(email)
        
        if 'admin' not in user_roles['roles']:
            raise HTTPException(status_code=404, detail="Admin not found")
        
        # Remove admin role
        success = await self.auth_dao.remove_user_role(email, 'admin')
        
        return {
            "success": success,
            "message": "Admin removed successfully"
        }

    async def add_admin(self, email: str) -> bool:
        """Add admin user"""
        try:
            result = await self.auth_dao.add_user_role(email, 'admin')
            return result is not None
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            raise
    
    async def add_human_agent(self, email: str) -> bool:
        """Add human agent"""
        try:
            result = await self.auth_dao.add_user_role(email, 'human_agent')
            return result is not None
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

    async def remove_human_agent(self, email: str, current_user_email: str) -> dict:
        """Remove a human agent"""
        # Check if current user is an admin
        current_user_roles = await self.get_user_role(current_user_email)
        
        if 'admin' not in current_user_roles['roles']:
            raise HTTPException(status_code=403, detail="Only admins can remove human agents")
        
        # Check if user has human agent role
        user_roles = await self.get_user_role(email)
        
        if 'human_agent' not in user_roles['roles']:
            raise HTTPException(status_code=404, detail="Human agent not found")
        
        # Remove human agent role
        success = await self.auth_dao.remove_user_role(email, 'human_agent')
        
        return {
            "success": success,
            "message": "Human agent removed successfully"
        }
