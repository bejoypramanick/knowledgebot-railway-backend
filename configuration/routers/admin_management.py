"""
Admin Management Endpoints
Handles admin user creation, verification, and role management.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from configuration.core.logging_config import get_railway_logger

from ..service.auth_service import AuthService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-management"])


class AdminRequest(BaseModel):
    emails: List[EmailStr]


@router.post("/admins", response_model=dict)
async def add_admins(request: AdminRequest):
    """Add admin users. Only existing admins can add new admins."""
    # Note: Authentication should be handled at the API Gateway level
    # This endpoint assumes the caller is already authenticated
    try:
        # For now, we'll use a placeholder email - in production, this should come from the authenticated user
        user_email = "system@admin.com"  # TODO: Get from authenticated context
        
        service = AuthService()  # Service manages its own DAO
        result = await service.add_admins(request.emails, user_email)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding admins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding admins: {str(e)}")


# Admin confirmation endpoint removed - admins are now activated immediately


@router.get("/admins", response_model=dict)
async def list_admins():
    """List all admins. Only admins can view this list."""
    # Note: Authentication should be handled at the API Gateway level
    try:
        auth_service = AuthService()  # Service manages its own DAO
        
        # Get all admins (authentication check should be done at API Gateway)
        admins = await auth_service.list_all_admins()
        
        return {
            "success": True,
                "admins": [
                    {
                        "email": admin['email'],
                        "created_at": admin['created_at'].isoformat() if admin['created_at'] else None,
                        "created_by": admin['created_by_email']
                    }
                    for admin in admins
                ]
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing admins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing admins: {str(e)}")


@router.delete("/admins/{email}", response_model=dict)
async def remove_admin(email: str):
    """Remove an admin. Only admins can remove other admins."""
    # Note: Authentication should be handled at the API Gateway level
    try:
        # For now, we'll use a placeholder email - in production, this should come from the authenticated user
        user_email = "system@admin.com"  # TODO: Get from authenticated context
        
        auth_service = AuthService()  # Service manages its own DAO
        result = await auth_service.remove_admin(email, user_email)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing admin: {str(e)}")


@router.get("/user-role/{email}", response_model=dict)
async def get_user_role(email: str):
    """Get user roles (admin, human_agent, or user) for a given email."""
    try:
        service = AuthService()  # Service manages its own DAO
        return await service.get_user_role(email)
    except Exception as e:
        logger.error(f"Error getting user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user role: {str(e)}")


@router.get("/users/roles", response_model=dict)
async def get_user_roles(token: str):
    """Get user roles by extracting email from Firebase token."""
    try:
        service = AuthService()  # Service manages its own DAO
        return await service.get_user_roles_from_token(token)
    except Exception as e:
        logger.error(f"Error getting user roles from token: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user roles: {str(e)}")
