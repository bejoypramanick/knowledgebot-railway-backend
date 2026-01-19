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
    Get user profile information from admins/human_agents tables.
    No longer uses user_profiles table.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:

            # First check if user is an admin
            admin_profile = await conn.fetchrow(
                """
                SELECT email, display_name, photo_url, role, created_at, last_login, preferences
                FROM admins
                WHERE email = $1 AND status = 'confirmed'
                """,
                current_user.get('email')
            )

            if admin_profile:
                # Parse preferences - handle both dict and string cases
                preferences = admin_profile['preferences']
                if isinstance(preferences, str):
                    try:
                        preferences = json.loads(preferences)
                    except (json.JSONDecodeError, TypeError):
                        preferences = {}
                elif preferences is None:
                    preferences = {}

                logger.info(f"👑 Returning admin profile for uid {uid}: email='{admin_profile['email']}'")
                return UserProfileResponse(
                    uid=uid,
                    email=admin_profile['email'],
                    display_name=admin_profile['display_name'] or current_user.get('name'),
                    photo_url=admin_profile['photo_url'] or current_user.get('picture'),
                    role=admin_profile['role'] or 'admin',
                    created_at=admin_profile['created_at'] or datetime.now(),
                    last_login=admin_profile['last_login'],
                    preferences=preferences
                )

            # Check if user is a human agent
            agent_profile = await conn.fetchrow(
                """
                SELECT email, display_name, photo_url, role, created_at, last_login, preferences
                FROM human_agents
                WHERE email = $1 AND status IN ('confirmed', 'pending')
                """,
                current_user.get('email')
            )

            if agent_profile:
                # Parse preferences - handle both dict and string cases
                preferences = agent_profile['preferences']
                if isinstance(preferences, str):
                    try:
                        preferences = json.loads(preferences)
                    except (json.JSONDecodeError, TypeError):
                        preferences = {}
                elif preferences is None:
                    preferences = {}

                logger.info(f"🤖 Returning human agent profile for uid {uid}: email='{agent_profile['email']}'")
                return UserProfileResponse(
                    uid=uid,
                    email=agent_profile['email'],
                    display_name=agent_profile['display_name'] or current_user.get('name'),
                    photo_url=agent_profile['photo_url'] or current_user.get('picture'),
                    role=agent_profile['role'] or 'human_agent',
                    created_at=agent_profile['created_at'] or datetime.now(),
                    last_login=agent_profile['last_login'],
                    preferences=preferences
                )

            # Regular user - return basic profile from Firebase
            logger.info(f"👤 Returning basic user profile for uid {uid} (no elevated roles)")
            return UserProfileResponse(
                uid=uid,
                email=current_user.get('email'),
                display_name=current_user.get('name'),
                photo_url=current_user.get('picture'),
                role='user',
                created_at=datetime.now(),
                preferences={}
            )

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
    Update user profile information in admins/human_agents tables.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:

            # Check if user is admin and update their profile
            admin_exists = await conn.fetchval(
                "SELECT 1 FROM admins WHERE email = $1 AND status = 'confirmed'",
                current_user.get('email')
            )

            if admin_exists:
                await conn.execute(
                    """
                    UPDATE admins
                    SET display_name = COALESCE($2, display_name),
                        photo_url = COALESCE($3, photo_url),
                        preferences = COALESCE($4, preferences),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE email = $1 AND status = 'confirmed'
                    """,
                    current_user.get('email'),
                    request.display_name if request else None,
                    request.photo_url if request else None,
                    request.preferences if request else None
                )
                logger.info(f"👑 Updated admin profile for {current_user.get('email')}")
                return await get_user_profile(uid, current_user)

            # Check if user is human agent and update their profile
            agent_exists = await conn.fetchval(
                "SELECT 1 FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')",
                current_user.get('email')
            )

            if agent_exists:
                await conn.execute(
                    """
                    UPDATE human_agents
                    SET display_name = COALESCE($2, display_name),
                        photo_url = COALESCE($3, photo_url),
                        preferences = COALESCE($4, preferences),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE email = $1 AND status IN ('confirmed', 'pending')
                    """,
                    current_user.get('email'),
                    request.display_name if request else None,
                    request.photo_url if request else None,
                    request.preferences if request else None
                )
                logger.info(f"🤖 Updated human agent profile for {current_user.get('email')}")
                return await get_user_profile(uid, current_user)

            # Regular user - no profile to update
            logger.info(f"👤 Cannot update profile for regular user {current_user.get('email')} (no elevated role)")
            raise HTTPException(
                status_code=403,
                detail="Profile updates are only available for admins and human agents"
            )

    except HTTPException:
        raise
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

            # Check admin and human_agent tables to determine all roles for the user
            logger.info(f"📊 Checking admin and human_agent tables for email: {current_user.get('email')}")

            roles = ['user']  # Everyone has user role as base

            # Check admin table
            admin_check = await conn.fetchrow(
                "SELECT status FROM admins WHERE email = $1 AND status = 'confirmed'",
                current_user.get('email')
            )

            if admin_check:
                roles.append('admin')
                logger.info(f"👑 Admin role confirmed for {current_user.get('email')}")

            # Check human_agent table
            agent_check = await conn.fetchrow(
                "SELECT status FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')",
                current_user.get('email')
            )

            if agent_check:
                roles.append('human_agent')
                logger.info(f"🤖 Human agent role confirmed for {current_user.get('email')}")

            logger.info(f"📋 Final roles for {current_user.get('email')}: {roles}")
            return roles

            # Default to user role
            roles = ['user']
            logger.info(f"👤 No elevated roles found for {current_user.get('email')} - returning roles: {roles}")
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
    Switch user role - this is mainly for UI state management.
    Actual role permissions are determined by admins/human_agents table membership.
    """
    try:
        role = request.role.lower() if request else 'user'
        if role not in ['customer', 'agent', 'admin']:
            raise HTTPException(status_code=400, detail="Invalid role. Must be 'customer', 'agent', or 'admin'")

        # Map 'customer' to 'user' for consistency
        if role == 'customer':
            role = 'user'

        logger.info(f"🔄 Role switch requested for {current_user.get('email')} to '{role}'")

        # Note: In the new architecture, roles are determined by table membership,
        # not by a stored role field. This endpoint mainly serves the frontend
        # state management and validation.

        return SwitchRoleResponse(
            success=True,
            message=f"Role switched to {role}. Note: Actual permissions are determined by your admin/human agent status."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching user role: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
