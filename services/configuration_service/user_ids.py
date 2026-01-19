"""
User Management Endpoints
Handles user profiles, roles, and unique IDs for users, agents, and admins.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
import logging
import sys
from pathlib import Path
from datetime import datetime
import uuid
import random
import string
import json

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UniqueIdRequest(BaseModel):
    email: Optional[str] = None
    role: str = 'customer'  # 'customer', 'agent', or 'admin'


class UniqueIdResponse(BaseModel):
    unique_id: str
    email: Optional[str] = None
    role: str
    created: bool  # True if newly created, False if existing


class UserProfileRequest(BaseModel):
    display_name: Optional[str] = None
    photo_url: Optional[str] = None
    preferences: Optional[dict] = None


class UserProfileResponse(BaseModel):
    uid: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    photo_url: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    preferences: Optional[dict] = None


class SwitchRoleRequest(BaseModel):
    role: str  # 'customer', 'agent', or 'admin'


class SwitchRoleResponse(BaseModel):
    success: bool
    message: str


def generate_unique_id(role: str) -> str:
    """Generate a unique ID with role prefix."""
    prefix = 'ADM' if role == 'admin' else ('AGT' if role == 'agent' else 'CUS')
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}-{timestamp}-{random_part}"


@router.post("/unique-id", response_model=UniqueIdResponse)
async def get_or_create_unique_id(
    request: UniqueIdRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Get or create a unique ID for a user.
    If email is provided, returns existing ID or creates new one.
    If email is None (anonymous user), creates a temporary ID.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            role = request.role.lower()
            if role not in ['customer', 'agent', 'admin']:
                raise HTTPException(status_code=400, detail="Role must be 'customer', 'agent', or 'admin'")
            
            # For anonymous users (no email), generate temporary ID
            if not request.email:
                temp_id = f"TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
                return UniqueIdResponse(
                    unique_id=temp_id,
                    email=None,
                    role=role,
                    created=True
                )
            
            # Check if unique ID already exists for this email and role
            existing = await conn.fetchrow(
                """
                SELECT unique_id, created_at 
                FROM user_unique_ids 
                WHERE email = $1 AND role = $2
                """,
                request.email, role
            )
            
            if existing:
                logger.info(f"Found existing unique ID for {request.email} ({role})")
                return UniqueIdResponse(
                    unique_id=existing['unique_id'],
                    email=request.email,
                    role=role,
                    created=False
                )
            
            # Generate new unique ID
            unique_id = generate_unique_id(role)
            
            # Ensure uniqueness (retry if collision)
            max_retries = 5
            for attempt in range(max_retries):
                existing_id = await conn.fetchval(
                    "SELECT unique_id FROM user_unique_ids WHERE unique_id = $1",
                    unique_id
                )
                if not existing_id:
                    break
                unique_id = generate_unique_id(role)
            
            # Insert new unique ID
            await conn.execute(
                """
                INSERT INTO user_unique_ids (email, unique_id, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (email, role) DO UPDATE
                SET updated_at = CURRENT_TIMESTAMP
                RETURNING unique_id
                """,
                request.email, unique_id, role
            )
            
            logger.info(f"Created new unique ID {unique_id} for {request.email} ({role})")
            return UniqueIdResponse(
                unique_id=unique_id,
                email=request.email,
                role=role,
                created=True
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting/creating unique ID: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/unique-id", response_model=UniqueIdResponse)
async def get_unique_id(
    email: Optional[str] = Query(None, description="User email"),
    role: str = Query('customer', description="User role"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get existing unique ID for a user.
    Returns 404 if not found.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            role = role.lower()
            if role not in ['customer', 'agent', 'admin']:
                raise HTTPException(status_code=400, detail="Role must be 'customer', 'agent', or 'admin'")
            
            if not email:
                raise HTTPException(status_code=400, detail="Email is required for GET request")
            
            result = await conn.fetchrow(
                """
                SELECT unique_id, role, created_at
                FROM user_unique_ids 
                WHERE email = $1 AND role = $2
                """,
                email, role
            )
            
            if not result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unique ID not found for email {email} with role {role}"
                )
            
            return UniqueIdResponse(
                unique_id=result['unique_id'],
                email=email,
                role=role,
                created=False
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting unique ID: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/profile", response_model=UserProfileResponse)
async def get_user_profile(
    uid: str = Query(..., description="User UID"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get user profile information.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Get user profile from database
            profile = await conn.fetchrow(
                """
                SELECT uid, email, display_name, photo_url, role, created_at, last_login, preferences
                FROM user_profiles
                WHERE uid = $1
                """,
                uid
            )

            if not profile:
                # Create basic profile for new user
                await conn.execute(
                    """
                    INSERT INTO user_profiles (uid, email, role, created_at)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                    ON CONFLICT (uid) DO NOTHING
                    """,
                    uid, current_user.get('email'), 'user'
                )

                # Return basic profile
                logger.info(f"🆕 No profile found for uid {uid}, returning basic profile with role='user'")
                return UserProfileResponse(
                    uid=uid,
                    email=current_user.get('email'),
                    display_name=current_user.get('name'),
                    photo_url=current_user.get('picture'),
                    role='user',
                    created_at=datetime.now(),
                    preferences={}
                )

            # Parse preferences - handle both dict and string cases
            preferences = profile['preferences']
            if isinstance(preferences, str):
                try:
                    preferences = json.loads(preferences)
                except (json.JSONDecodeError, TypeError):
                    preferences = {}
            elif preferences is None:
                preferences = {}

            profile_response = UserProfileResponse(
                uid=profile['uid'],
                email=profile['email'],
                display_name=profile['display_name'],
                photo_url=profile['photo_url'],
                role=profile['role'] or 'user',
                created_at=profile['created_at'],
                last_login=profile['last_login'],
                preferences=preferences
            )

            logger.info(f"📄 Returning user profile for uid {uid}: role='{profile_response.role}', email='{profile_response.email}'")
            return profile_response

    except Exception as e:
        logger.error(f"Error getting user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/profile", response_model=UserProfileResponse)
async def update_user_profile(
    uid: str = Query(..., description="User UID"),
    request: UserProfileRequest = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Update user profile information.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Update user profile
            await conn.execute(
                """
                INSERT INTO user_profiles (uid, email, display_name, photo_url, preferences, updated_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (uid) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    photo_url = EXCLUDED.photo_url,
                    preferences = EXCLUDED.preferences,
                    updated_at = CURRENT_TIMESTAMP
                """,
                uid,
                current_user.get('email'),
                request.display_name if request else None,
                request.photo_url if request else None,
                request.preferences if request else {}
            )

            # Return updated profile
            return await get_user_profile(uid, current_user)

    except Exception as e:
        logger.error(f"Error updating user profile: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/roles", response_model=List[str])
async def get_user_roles(
    uid: str = Query(..., description="User UID"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get available roles for a user.
    This is a simplified implementation that returns basic roles.
    In a real implementation, this would check user permissions.
    """
    logger.info(f"🔍 get_user_roles called with uid: {uid}")
    logger.info(f"👤 Current user from auth: {current_user}")

    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Check if user_profiles table exists
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'user_profiles'
                )
                """
            )

            if not table_exists:
                logger.warning(f"⚠️ user_profiles table does not exist! Returning default roles for uid: {uid}")
                return ['user']

            # Get user role from profile
            logger.info(f"📊 Querying user_profiles table for uid: {uid}")
            role_result = await conn.fetchval(
                "SELECT role FROM user_profiles WHERE uid = $1",
                uid
            )

            user_role = role_result or 'user'
            logger.info(f"🎭 Database role for uid {uid}: '{role_result}' -> normalized to: '{user_role}'")

            # Return available roles based on current role
            if user_role == 'admin':
                roles = ['admin', 'human_agent', 'user']
                logger.info(f"👑 Admin user {uid} - returning roles: {roles}")
                return roles
            elif user_role == 'human_agent':
                roles = ['human_agent', 'user']
                logger.info(f"🤖 Human agent user {uid} - returning roles: {roles}")
                return roles
            else:
                roles = ['user']
                logger.info(f"👤 Regular user {uid} - returning roles: {roles}")
                return roles

    except Exception as e:
        logger.error(f"Error getting user roles: {e}")
        # Return default roles on error
        return ['user']


@router.post("/switch-role", response_model=SwitchRoleResponse)
async def switch_user_role(
    uid: str = Query(..., description="User UID"),
    request: SwitchRoleRequest = None,
    current_user: dict = Depends(get_current_user)
):
    """
    Switch user role.
    """
    try:
        role = request.role.lower() if request else 'user'
        if role not in ['customer', 'agent', 'admin']:
            raise HTTPException(status_code=400, detail="Invalid role. Must be 'customer', 'agent', or 'admin'")

        # Map 'customer' to 'user' for consistency
        if role == 'customer':
            role = 'user'

        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Update user role
            await conn.execute(
                """
                UPDATE user_profiles
                SET role = $2, updated_at = CURRENT_TIMESTAMP
                WHERE uid = $1
                """,
                uid, role
            )

            return SwitchRoleResponse(
                success=True,
                message=f"Role switched to {role}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching user role: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
