"""
Optimized Authentication Endpoints
Handles Firebase Auth token verification and user management with performance improvements.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import logging
import sys
from pathlib import Path
import time
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.firebase_auth import (
    verify_firebase_token,
    get_user_by_uid,
    init_firebase_auth,
    get_user_from_firestore,
    save_user_to_firestore,
    update_user_role_in_firestore
)
from shared.auth_middleware import get_current_user
from shared.db import get_db_connection
from shared.utils import retry_database_operation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

class TokenVerificationRequest(BaseModel):
    id_token: str

class TokenVerificationResponse(BaseModel):
    valid: bool
    user: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=0.5, max=4))
async def execute_role_query_with_retry(conn, query: str, email: str) -> list:
    """
    Execute database role query with retry logic.
    Retries up to 3 times with exponential backoff.
    """
    return await conn.fetch(query, email)


async def execute_database_operations_with_retry(email: str) -> tuple:
    """
    Execute all database operations with enhanced retry logic and connection handling.
    Uses the new DatabaseManager for robust database access.
    Returns (roles_result, db_time)
    """
    db_start_time = time.time()

    async with get_db_connection() as conn:
        # DEBUG: Check admin table for this user
        admin_check = await conn.fetchrow(
            "SELECT email FROM admins WHERE email = $1",
            email
        )
        if admin_check:
            logger.info(f"👑 Admin table entry found for {email}")
        else:
            logger.info(f"❌ No admin table entry found for {email}")

        # DEBUG: Check human_agents table for this user
        agent_check = await conn.fetchrow(
            "SELECT email FROM human_agents WHERE email = $1",
            email
        )
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
        roles_result = await execute_role_query_with_retry(conn, role_query, email)
        db_time = time.time() - db_start_time

        # Log what roles were found in database
        db_roles = [row['role'] for row in roles_result]
        logger.info(f"📊 Database roles found for {email}: {db_roles}")
        if not db_roles:
            logger.info(f"❌ No roles found in database for {email} - user will default to 'user' role")
            logger.info(f"💡 To grant admin access, ensure {email} is in the admins table")

        return roles_result, db_time

@router.post("/verify-token", response_model=TokenVerificationResponse)
async def verify_token_optimized(request_data: Dict[str, Any]):
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
            return TokenVerificationResponse(
                valid=False,
                message="id_token is required"
            )

        # Create request object for compatibility
        from pydantic import BaseModel
        class TempRequest(BaseModel):
            id_token: str

        request = TempRequest(id_token=id_token)
        # Step 1: Verify Firebase token
        decoded_token = verify_firebase_token(request.id_token)
        
        if not decoded_token:
            return TokenVerificationResponse(
                valid=False,
                message="Invalid or expired token"
            )
        
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
            user_data = {
                'email': email,
                'display_name': decoded_token.get('name'),
                'photo_url': decoded_token.get('picture'),
                'role': 'user',
                'roles': ['user'],
                'primary_role': 'user',
                'is_admin': False,
                'is_human_agent': False
            }
            logger.info(f"📋 Using default Firebase Auth data: role='user', roles=['user']")
        
        # Step 4: OPTIMIZED - Single database query for all roles
        user_roles = user_data.get('roles', [])
        primary_role = user_data.get('role', 'user')
        is_admin = False
        is_human_agent = False

        # Validate email is available
        if not email:
            raise HTTPException(
                status_code=400,
                detail="Email not available from Firebase token"
            )

        # Execute database operations with retry logic
        roles_result, db_time = await execute_database_operations_with_retry(email)

        logger.info(f"Database query took {db_time:.3f}s for email: {email}")

        # Process results
        for row in roles_result:
            role = row['role']
            if role == 'admin':
                is_admin = True
                primary_role = 'admin'  # Admin takes precedence
                if 'admin' not in user_roles:
                    user_roles.append('admin')
            elif role == 'human_agent':
                is_human_agent = True
                if primary_role == 'user':
                    primary_role = 'human_agent'
                if 'human_agent' not in user_roles:
                    user_roles.append('human_agent')

        # Ensure 'user' is in roles
        if 'user' not in user_roles:
            user_roles.append('user')

        # Update user_data with latest roles from DB
        user_data['role'] = primary_role
        user_data['primary_role'] = primary_role
        user_data['roles'] = user_roles
        user_data['is_admin'] = is_admin
        user_data['is_human_agent'] = is_human_agent

        # Detailed logging for debugging authorization issues
        logger.info(f"🎯 FINAL ROLE DETERMINATION for {email}:")
        logger.info(f"   - Primary role: '{primary_role}'")
        logger.info(f"   - All roles: {user_roles}")
        logger.info(f"   - Is admin: {is_admin}")
        logger.info(f"   - Is human agent: {is_human_agent}")
        logger.info(f"   - User data role field: '{user_data.get('role')}'")
        logger.info(f"   - Frontend will see: primary_role='{primary_role}', roles={user_roles}")

        total_time = time.time() - start_time
        logger.info(f"verify-token completed in {total_time:.3f}s for email: {email}")

        return TokenVerificationResponse(
            valid=True,
            user=user_data
        )
        
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Error verifying token after {total_time:.3f}s: {e}")
        return TokenVerificationResponse(
            valid=False,
            message=f"Error: {str(e)}"
        )


@router.post("/sync-user")
async def sync_user(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Sync Firebase Auth user to Firestore.
    Called after user signs up or logs in.
    Determines user role from database (admin, human_agent, or user).
    """
    try:
        firebase_uid = user.get('uid')
        email = user.get('email')
        
        if not firebase_uid or not email:
            raise HTTPException(status_code=400, detail="Missing uid or email in token")
        
        # Get existing user from Firestore
        existing_user = get_user_from_firestore(firebase_uid)
        
        # Determine all user roles from database (user can have multiple roles)
        user_roles = []  # List of all roles user has
        primary_role = 'user'  # Default primary role
        is_admin = False
        is_human_agent = False
        
        try:
            # Use new DatabaseManager for connection
            async with get_db_connection() as conn:
                # Check if user is an admin (status removed)
                admin = await conn.fetchrow(
                    "SELECT email FROM admins WHERE email = $1",
                    email
                )
                if admin:
                    user_roles.append('admin')
                    is_admin = True
                    primary_role = 'admin'  # Admin takes precedence
                
                # Check if user is a human agent (status removed)
                agent = await conn.fetchrow(
                    "SELECT email FROM human_agents WHERE email = $1",
                    email
                )
                if agent:
                    user_roles.append('human_agent')
                    is_human_agent = True
                    if primary_role == 'user':
                        primary_role = 'human_agent'
        except Exception as role_error:
            logger.error(f"Error determining user roles from database: {role_error}")
            raise HTTPException(status_code=503, detail="Unable to verify user roles - database service unavailable")
        
        # Ensure 'user' role is always present
        if 'user' not in user_roles:
            user_roles.append('user')
        
        # If no roles found, default to user
        if not user_roles:
            user_roles = ['user']
            primary_role = 'user'
        
        # Preserve role if user already exists in Firestore (unless database says otherwise)
        if existing_user and 'role' in existing_user:
            # Only update if database has a different primary role (database is source of truth)
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
            raise HTTPException(status_code=500, detail="Failed to save user to Firestore")
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user: {e}")
        raise HTTPException(status_code=500, detail=f"Error syncing user: {str(e)}")
