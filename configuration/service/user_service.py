"""
User Service Layer
Provides business logic for user management operations
"""
from typing import Any, Dict, Optional

from shared.logging_config import get_railway_logger
from shared.dao.user_dao import UserDAO

logger = get_railway_logger(__name__)

class UserService:
    """Service layer for user management"""
    
    def __init__(self):
        self.user_dao = UserDAO()  # Use shared UserDAO
    
    async def get_or_create_unique_id(self, email: Optional[str], role: str) -> Dict[str, Any]:
        """Get or create a unique ID for a user."""
        try:
            role = role.lower()
            if role not in ['customer', 'agent', 'admin']:
                raise ValueError("Role must be 'customer', 'agent', or 'admin'")
            
            # For anonymous users (no email), generate temporary ID
            if not email:
                import datetime
                import random
                import string
                temp_id = f"TEMP-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
                return {
                    'unique_id': temp_id,
                    'email': None,
                    'role': role,
                    'created': True
                }
            
            # Check if unique ID already exists for this email and role
            existing = await self.user_dao.get_unique_id_by_email_role(email, role)
            
            if existing:
                logger.info(f"Found existing unique ID for {email} ({role})")
                return {
                    'unique_id': existing['unique_id'],
                    'email': email,
                    'role': role,
                    'created': False
                }
            
            # Generate new unique ID
            unique_id = self._generate_unique_id(role)
            
            # Ensure uniqueness (retry if collision)
            max_retries = 5
            for attempt in range(max_retries):
                existing_id = await self.user_dao.check_unique_id_exists(unique_id)
                if not existing_id:
                    break
                unique_id = self._generate_unique_id(role)
            
            # Insert new unique ID
            await self.user_dao.create_unique_id(email, unique_id, role)
            
            logger.info(f"Created new unique ID {unique_id} for {email} ({role})")
            
            return {
                'unique_id': unique_id,
                'email': email,
                'role': role,
                'created': True
            }
        except Exception as e:
            logger.error(f"Error getting/creating unique ID: {e}")
            raise
    
    def _generate_unique_id(self, role: str) -> str:
        """Generate a new unique ID."""
        import random
        import string
        import uuid
        
        prefix = {
            'customer': 'CUST',
            'agent': 'AGENT', 
            'admin': 'ADMIN'
        }.get(role, 'USER')
        
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return f"{prefix}-{random_part}-{uuid.uuid4().hex[:8]}"
    
    async def get_unique_id(self, email: str, role: str) -> Optional[Dict[str, Any]]:
        """Get existing unique ID for a user."""
        try:
            role = role.lower()
            if role not in ['customer', 'agent', 'admin']:
                raise ValueError("Role must be 'customer', 'agent', or 'admin'")
            
            if not email:
                raise ValueError("Email is required for GET request")
            
            result = await self.user_dao.get_unique_id_by_email_role(email, role)
            
            if not result:
                return None
            
            return {
                'unique_id': result['unique_id'],
                'email': email,
                'role': role,
                'created': False
            }
        except Exception as e:
            logger.error(f"Error getting unique ID: {e}")
            raise
    
    async def get_user_profile(self, user_email: str) -> Dict[str, Any]:
        """Get user profile with role priority."""
        try:
            # Get user role with priority: admin > human_agent > user
            role = await self.user_dao.get_user_role_priority(user_email)
            
            return {
                'email': user_email,
                'role': role,
                'is_admin': role == 'admin',
                'is_human_agent': role == 'human_agent',
                'is_customer': role == 'user'
            }
        except Exception as e:
            logger.error(f"Error getting user profile: {e}")
            raise
    
    async def check_admin_permissions(self, user_email: str) -> bool:
        """Check if user has admin permissions."""
        try:
            is_admin = await self.user_dao.is_admin(user_email)
            return bool(is_admin)
        except Exception as e:
            logger.error(f"Error checking admin permissions: {e}")
            raise
    
    async def get_current_user_info(self, user_email: str) -> Dict[str, Any]:
        """Get current user information including roles."""
        try:
            user_email = user_email
            logger.info(f"📊 Checking admin and human_agent tables for email: {user_email}")
            
            # Check if user is admin
            is_admin = await self.user_dao.is_admin(user_email)
            
            # Check if user is human agent
            is_human_agent = await self.user_dao.is_human_agent(user_email)
            
            # Determine primary role with priority
            if is_admin:
                role = 'admin'
            elif is_human_agent:
                role = 'human_agent'
            else:
                role = 'user'
            
            return {
                'email': user_email,
                'role': role,
                'is_admin': bool(is_admin),
                'is_human_agent': bool(is_human_agent),
                'is_customer': role == 'user'
            }
        except Exception as e:
            logger.error(f"Error getting current user info: {e}")
            raise
