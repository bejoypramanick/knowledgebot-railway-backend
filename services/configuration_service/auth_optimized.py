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
from shared.db import railway_db, DatabaseConnection
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


@retry_database_operation
async def execute_database_operations_with_retry(email: str) -> tuple:
    """
    Execute all database operations with enhanced retry logic and connection handling.
    Uses the new DatabaseConnection context manager for robust database access.
    Returns (roles_result, db_time)
    """
    db_start_time = time.time()

    async with DatabaseConnection() as conn:
        # OPTIMIZED: Single query with UNION instead of multiple queries
        role_query = """
            SELECT role FROM (
                SELECT 'admin' as role, email FROM admins WHERE email = $1 AND status = 'confirmed'
                UNION ALL
                SELECT 'human_agent' as role, email FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')
            ) user_roles
            WHERE email = $1
        """

        # Execute with retry logic - throws exact error if all retries fail
        roles_result = await execute_role_query_with_retry(conn, role_query, email)
        db_time = time.time() - db_start_time

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
        user_data = get_user_from_firestore(uid)
        
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

# Keep the original endpoint as fallback
@router.post("/verify-token-original", response_model=TokenVerificationResponse)
async def verify_token(request: TokenVerificationRequest):
    """
    Original Firebase Auth token verification (kept for comparison).
    This endpoint is used by frontend to verify tokens.
    """
    try:
        decoded_token = verify_firebase_token(request.id_token)
        
        if not decoded_token:
            return TokenVerificationResponse(
                valid=False,
                message="Invalid or expired token"
            )
        
        # Get user from Firestore
        uid = decoded_token.get('uid')
        email = decoded_token.get('email')
        user_data = get_user_from_firestore(uid)
        
        # If user doesn't exist in Firestore, return Firebase Auth data
        if not user_data:
            user_data = {
                'uid': uid,
                'email': email,
                'email_verified': decoded_token.get('email_verified', False),
                'display_name': decoded_token.get('name'),
                'photo_url': decoded_token.get('picture'),
                'role': 'user',
                'roles': ['user'],
                'primary_role': 'user',
                'is_admin': False,
                'is_human_agent': False
            }
        
        # Helper variables for role check
        user_roles = user_data.get('roles', [])
        primary_role = user_data.get('role', 'user')
        is_admin = user_data.get('is_admin', False)
        is_human_agent = user_data.get('is_human_agent', False)
        
        # Check database for exact roles (source of truth) - REQUIRED, no fallback
        if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
            raise HTTPException(
                status_code=503,
                detail="Database connection unavailable - authentication service is down"
            )

        if not email:
            raise HTTPException(
                status_code=400,
                detail="Email not available from Firebase token"
            )

        async with railway_db.acquire() as conn:
            # Check if user is an admin
            admin = await conn.fetchrow(
                "SELECT email FROM admins WHERE email = $1 AND status = 'confirmed'",
                email
            )
            if admin:
                if 'admin' not in user_roles:
                    user_roles.append('admin')
                is_admin = True
                primary_role = 'admin'  # Admin takes precedence

            # Check if user is a human agent (recognize both confirmed and pending)
            agent = await conn.fetchrow(
                "SELECT email FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')",
                email
            )
            if agent:
                if 'human_agent' not in user_roles:
                    user_roles.append('human_agent')
                is_human_agent = True
                if primary_role == 'user':
                    primary_role = 'human_agent'

        # Ensure 'user' is in roles
        if 'user' not in user_roles:
            user_roles.append('user')

        # Update user_data with latest roles from DB
        user_data['role'] = primary_role
        user_data['primary_role'] = primary_role
        user_data['roles'] = user_roles
        user_data['is_admin'] = is_admin
        user_data['is_human_agent'] = is_human_agent
        
        return TokenVerificationResponse(
            valid=True,
            user=user_data
        )
        
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        return TokenVerificationResponse(
            valid=False,
            message=f"Error: {str(e)}"
        )
