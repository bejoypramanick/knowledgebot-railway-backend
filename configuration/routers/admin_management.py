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


@router.get("/user-role/{email}", response_model=dict)
async def get_user_role(email: str):
    """Get user roles (admin, human_agent, or user) for a given email."""
    try:
        service = AuthService()  # Service manages its own DAO
        return await service.get_user_role(email)
    except Exception as e:
        logger.error(f"Error getting user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user role: {str(e)}")
