"""
Auth Service Layer
Provides business logic for authentication operations
"""
from typing import Any, Dict, List, Optional
from fastapi import HTTPException

from configuration.core.otel_logger import get_otel_logger

from ..dao.auth_dao import AuthDAO

logger = get_otel_logger("auth_service", "configuration")

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
    
    async def check_human_agent_exists(self, email: str) -> bool:
        """Check if human agent exists"""
        try:
            return await self.auth_dao.check_human_agent_exists(email)
        except Exception as e:
            logger.error(f"Error checking human agent: {e}")
            raise
    
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
        admin_result = await self.check_admin_exists(current_user_email)
        
        if not admin_result:
            raise HTTPException(status_code=403, detail="Only admins can remove other admins")
        
        # Check if admin exists
        admin = await self.check_admin_exists(email)
        
        if not admin:
            raise HTTPException(status_code=404, detail="Admin not found")
        
        # Remove admin
        await self.auth_dao.remove_admin(email)
        
        return {
            "success": True,
            "message": "Admin removed successfully"
        }

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

    async def remove_human_agent(self, email: str, current_user_email: str) -> dict:
        """Remove a human agent"""
        try:
            await self.auth_dao.remove_human_agent(email)
            return {"success": True, "message": "Human agent removed successfully"}
        except Exception as e:
            logger.error(f"Error removing human agent: {e}")
            raise
