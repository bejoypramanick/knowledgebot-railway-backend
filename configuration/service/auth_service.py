"""
Auth Service Layer
Provides business logic for authentication operations
"""
from typing import Any, Dict, List, Optional

from shared.logging_config import get_railway_logger

from ..dao.auth_dao import AuthDAO

logger = get_railway_logger(__name__)

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
            return False

    async def add_admins(self, emails: List[str], current_user_email: str) -> dict:
        """Add multiple admin users with business logic"""
        # Check if current user is an admin
        is_admin = await self.check_admin_exists(current_user_email)
        
        if not is_admin or is_admin == 0:
            raise HTTPException(status_code=403, detail="Only admins can add new admins")
        
        # Create admins directly without email confirmation
        admins_created = []
        
        for email in emails:
            # Check if admin already exists
            existing = await self.check_admin_exists(email)

            if existing:
                logger.info(f"Admin {email} already exists, skipping")
                continue
            
            # Create new admin
            import secrets
            token = secrets.token_urlsafe(32)
            admin_id = await self.add_admin(email)
            
            # Admin created successfully
            admins_created.append({
                "email": email,
                "status": "active",
                "confirmation_token": token
            })
            logger.info(f"Admin {email} created successfully")
        
        return {
            "success": True,
            "message": "Admins created successfully",
            "admins": admins_created
        }

    async def get_user_roles_from_token(self, token: str) -> dict:
        """Get user roles by extracting email from Firebase token"""
        try:
            # Import here to avoid circular imports
            import httpx
            import os
            
            # Get user email from Firebase token via API Gateway
            api_gateway_url = os.getenv("API_GATEWAY_URL", "http://localhost:8080")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{api_gateway_url}/firebase/verify-token",
                    json={"token": token}
                )
                
                if response.status_code != 200:
                    return {"roles": ["user"], "error": "Invalid token"}
                
                token_data = response.json()
                
                if not token_data or 'email' not in token_data:
                    return {"roles": ["user"], "error": "Token missing email"}
                
                email = token_data['email']
                
                # Get roles using email
                result = await self.get_user_role(email)
                return result
        except Exception as e:
            logger.error(f"Error getting user roles from token: {e}")
            return {"roles": ["user"], "error": str(e)}

    async def get_user_role(self, email: str) -> dict:
        """Get user role (admin, human_agent, or user) for a given email"""
        try:
            roles = []
            
            # Check if user is an admin
            is_admin = await self.check_admin_exists(email)
            if is_admin:
                roles.append("admin")
            
            # Check if user is a human agent
            is_agent = await self.check_human_agent_exists(email)
            if is_agent:
                roles.append("human_agent")
            
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
        is_admin = await self.check_admin_exists(current_user_email)
        
        if not is_admin or is_admin == 0:
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
