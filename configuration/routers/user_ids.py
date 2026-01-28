"""
User Management Endpoints
Handles user profiles, roles, and unique IDs for users, agents, and admins.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
import logging
import uuid
import random
import string
import json

from shared.auth_middleware import get_current_user
from ..service.user_service import UserService

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
        user_service = UserService()  # Service manages its own DAO
        
        result = await user_service.get_or_create_unique_id(request.email, request.role)
        
        return UniqueIdResponse(
            unique_id=result['unique_id'],
            email=result['email'],
            role=result['role'],
            created=result['created']
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
        user_service = UserService()  # Service manages its own DAO
        
        result = await user_service.get_unique_id(email, role)
        
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
    Uses Firebase data for display_name and photo_url, no local storage.
    No user-specific preferences since all changes are global.
    """
    try:
        user_service = UserService()  # Service manages its own DAO
        
        profile = await user_service.get_user_profile(current_user.get('email'))
        
        return UserProfileResponse(
            uid=uid,
            email=profile['email'],
            display_name=current_user.get('name'),  # From Firebase
            photo_url=current_user.get('picture'),  # From Firebase
            role=profile['role'],
            created_at=None,  # Service doesn't provide this
            preferences={}  # No user-specific preferences
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
    Update user profile information - only for admins and human agents.
    Since display_name, photo_url come from Firebase, and there are no user preferences,
    this endpoint mainly validates that the user exists and has proper permissions.
    """
    try:
        user_service = UserService()  # Service manages its own DAO
        
        # Check if user is admin
        is_admin = await user_service.check_admin_permissions(current_user.get('email'))
        
        if is_admin:
            # For admins, we don't update any fields since display_name/photo_url come from Firebase
            # and there are no user-specific preferences. Just return the current profile.
            logger.info(f"👑 Admin profile access validated for {current_user.get('email')}")
            return await get_user_profile(uid, current_user)

        # Check if user is human agent (we can add this logic later if needed)
        # For now, just return the current profile for non-admins
        logger.info(f"👤 User profile access validated for {current_user.get('email')}")
        return await get_user_profile(uid, current_user)
    
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
    logger.info(f"🔍 get_user_roles called with uid: {uid}")
    logger.info(f"👤 Current user from auth: {current_user}")

    try:
        user_service = UserService()  # Service manages its own DAO
        
        user_info = await user_service.get_current_user_info(current_user.get('email'))
        
        # Return the user's role as a list
        roles = [user_info['role']]
        
        # If user has no valid role, deny access
        if user_info['role'] == 'user':
            logger.warning(f"🚫 User {current_user.get('email')} has no elevated roles - access denied")
            raise HTTPException(status_code=403, detail="Access denied: No valid roles found")
        
        logger.info(f"📋 Final roles for {current_user.get('email')}: {roles}")
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
