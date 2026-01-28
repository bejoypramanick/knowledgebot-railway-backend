"""
Auth Optimized Service Layer for Configuration
Provides business logic for optimized authentication operations
"""
import logging
import time
from typing import Optional, Dict, Any, List, Tuple
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.firebase_auth import (
    verify_firebase_token,
    get_user_by_uid,
    init_firebase_auth,
    get_user_from_firestore,
    save_user_to_firestore,
    update_user_role_in_firestore
)
from ..service.auth_service import AuthService

logger = logging.getLogger(__name__)

class AuthOptimizedService:
    """Service layer for optimized authentication operations"""
    
    def __init__(self):
        self.auth_service = AuthService()  # Service manages its own DAO
    
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=0.5, max=4))
    async def execute_role_query_with_retry(self, query: str, email: str) -> list:
        """
        Execute database role query with retry logic.
        Retries up to 3 times with exponential backoff.
        """
        return await self.auth_service.execute_role_query(query, email)

    async def execute_database_operations_with_retry(self, email: str) -> Tuple[list, float]:
        """
        Execute all database operations with enhanced retry logic and connection handling.
        Uses the new DatabaseManager for robust database access.
        Returns (roles_result, db_time)
        """
        db_start_time = time.time()
        
        # DEBUG: Check admin table for this user
        admin_check = await self.auth_service.check_admin_exists(email)
        if admin_check:
            logger.info(f"👑 Admin table entry found for {email}")
        else:
            logger.info(f"❌ No admin table entry found for {email}")

        # DEBUG: Check human_agents table for this user
        agent_check = await self.auth_service.check_human_agent_exists(email)
        if agent_check:
            logger.info(f"🤖 Human agent table entry found for {email}")
        else:
            logger.info(f"❌ No human agent table entry found for {email}")

        # OPTIMIZED: Single query with UNION instead of multiple queries (status removed)
        role_query = """
            SELECT role FROM (
                SELECT 'admin' as role, email FROM admins WHERE email = $1
                UNION ALL
                SELECT 'human_agent' as role, email FROM human_agents WHERE email = $1
            ) user_roles
            WHERE email = $1
        """

        # Execute with retry logic - throws exact error if all retries fail
        roles_result = await self.auth_service.execute_role_query(role_query, email)
        db_time = time.time() - db_start_time

        # Log what roles were found in database
        db_roles = [row['role'] for row in roles_result]
        logger.info(f"📊 Database roles found for {email}: {db_roles}")
        if not db_roles:
            logger.info(f"❌ No roles found in database for {email} - user will default to 'user' role")
            logger.info(f"💡 To grant admin access, ensure {email} is in the admins table")

        return roles_result, db_time

    async def verify_token_optimized(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Optimized Firebase Auth token verification with single database query.
        This endpoint is used by frontend to verify tokens.
        """
        start_time = time.time()

        try:
            # Debug logging to understand the request
            logger.info(f"verify-token called with request_data: {request_data}")

            # Extract id_token from request data
            id_token = request_data.get('id_token')
            if not id_token:
                return {
                    "valid": False,
                    "message": "id_token is required"
                }

            # Create request object for compatibility
            from pydantic import BaseModel
            class TempRequest(BaseModel):
                id_token: str

            request = TempRequest(id_token=id_token)
            
            # Step 1: Verify Firebase token
            decoded_token = verify_firebase_token(request.id_token)
            
            if not decoded_token:
                return {
                    "valid": False,
                    "message": "Invalid or expired token"
                }
            
            # Step 2: Get user from Firestore
            uid = decoded_token.get('uid')
            email = decoded_token.get('email')
            logger.info(f"🔐 Token verification for email: {email}, uid: {uid}")

            user_data = get_user_from_firestore(uid)

            if user_data:
                logger.info(f"📋 Firestore user data found: role='{user_data.get('role')}', roles={user_data.get('roles', [])}")
            else:
                logger.info(f"📋 No Firestore user data found - using Firebase Auth defaults")

            # Step 3: If user doesn't exist in Firestore, return Firebase Auth data
            if not user_data:
                return {
                    "valid": True,
                    "user": {
                        "uid": uid,
                        "email": email,
                        "name": decoded_token.get('name'),
                        "email_verified": decoded_token.get('email_verified', False),
                        "picture": decoded_token.get('picture'),
                        "role": "user",  # Default role
                        "roles": ["user"],
                        "is_admin": False,
                        "is_human_agent": False
                    }
                }

            # Step 4: Sync user roles from database
            roles_result, db_time = await self.execute_database_operations_with_retry(email)
            
            # Process roles and update user data
            user_roles = [row['role'] for row in roles_result]
            is_admin = 'admin' in user_roles
            is_human_agent = 'human_agent' in user_roles
            
            # Determine primary role
            primary_role = 'user'
            if is_admin:
                primary_role = 'admin'
            elif is_human_agent:
                primary_role = 'human_agent'
            
            # Check if role needs updating in Firestore
            existing_user = user_data
            if primary_role != existing_user.get('role'):
                logger.info(f"Updating user role from {existing_user.get('role')} to {primary_role} based on database")
            else:
                primary_role = existing_user.get('role')
            
            # Prepare user data
            updated_user_data = {
                'email': email,
                'display_name': user_data.get('name'),
                'email_verified': user_data.get('email_verified', False),
                'photo_url': user_data.get('picture'),
                'role': primary_role,  # Primary role for backward compatibility
                'primary_role': primary_role,
                'roles': user_roles,  # All available roles
                'is_admin': is_admin,
                'is_human_agent': is_human_agent,
            }
            
            # Save to Firestore
            success = save_user_to_firestore(uid, updated_user_data)
            
            if not success:
                raise Exception("Failed to save user to Firestore")
            
            logger.info(f"User {uid} synced to Firestore with roles: {user_roles}, primary: {primary_role}")
            
            total_time = time.time() - start_time
            logger.info(f"✅ Token verification completed in {total_time:.3f}s (DB: {db_time:.3f}s)")
            
            return {
                "valid": True,
                "user": {
                    "uid": uid,
                    "email": email,
                    "name": user_data.get('name'),
                    "email_verified": user_data.get('email_verified', False),
                    "picture": user_data.get('picture'),
                    "role": primary_role,  # For backward compatibility
                    "primary_role": primary_role,
                    "roles": user_roles,  # All available roles
                    "is_admin": is_admin,
                    "is_human_agent": is_human_agent
                }
            }
            
        except Exception as e:
            logger.error(f"Error in token verification: {e}", exc_info=True)
            return {
                "valid": False,
                "message": f"Token verification failed: {str(e)}"
            }

    async def sync_user_roles(self, firebase_uid: str) -> Dict[str, Any]:
        """
        Sync user roles from database to Firestore.
        """
        try:
            # Get user from Firestore
            user = get_user_from_firestore(firebase_uid)
            if not user:
                raise Exception("User not found in Firestore")
            
            email = user.get('email')
            if not email:
                raise Exception("User email not found")
            
            # Get roles from database
            roles_result, db_time = await self.execute_database_operations_with_retry(email)
            
            # Process roles
            user_roles = [row['role'] for row in roles_result]
            is_admin = 'admin' in user_roles
            is_human_agent = 'human_agent' in user_roles
            
            # Determine primary role
            primary_role = 'user'
            if is_admin:
                primary_role = 'admin'
            elif is_human_agent:
                primary_role = 'human_agent'
            
            # Check if role needs updating
            existing_user = user
            if primary_role != existing_user.get('role'):
                logger.info(f"Updating user role from {existing_user.get('role')} to {primary_role} based on database")
            else:
                primary_role = existing_user.get('role')
            
            # Prepare user data
            user_data = {
                'email': email,
                'display_name': user.get('name'),
                'email_verified': user.get('email_verified', False),
                'photo_url': user.get('picture'),
                'role': primary_role,  # Primary role for backward compatibility
                'primary_role': primary_role,
                'roles': user_roles,  # All available roles
                'is_admin': is_admin,
                'is_human_agent': is_human_agent,
            }
            
            # Save to Firestore
            success = save_user_to_firestore(firebase_uid, user_data)
            
            if not success:
                raise Exception("Failed to save user to Firestore")
            
            logger.info(f"User {firebase_uid} synced to Firestore with roles: {user_roles}, primary: {primary_role}")
            return {
                "success": True, 
                "message": "User synced successfully", 
                "role": primary_role,  # For backward compatibility
                "primary_role": primary_role,
                "roles": user_roles,  # All available roles
                "is_admin": is_admin,
                "is_human_agent": is_human_agent
            }
            
        except Exception as e:
            logger.error(f"Error syncing user roles: {e}", exc_info=True)
            raise

# Singleton instance
auth_optimized_service = AuthOptimizedService()
