"""
Optimized Authentication Endpoints
Handles Firebase Auth token verification and user management with performance improvements.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import logging

from shared.auth_middleware import get_current_user
from ..service.auth_optimized_service import auth_optimized_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])

class TokenVerificationRequest(BaseModel):
    id_token: str

class TokenVerificationResponse(BaseModel):
    valid: bool
    user: Optional[Dict[str, Any]] = None
    message: Optional[str] = None

@router.post("/verify-token", response_model=TokenVerificationResponse)
async def verify_token_optimized(request_data: Dict[str, Any]):
    """
    Optimized Firebase Auth token verification with single database query.
    This endpoint is used by frontend to verify tokens.
    """
    try:
        # Service handles all business logic
        result = await auth_optimized_service.verify_token_optimized(request_data)
        
        return TokenVerificationResponse(**result)
        
    except Exception as e:
        logger.error(f"Error in token verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Token verification failed: {str(e)}")

@router.post("/sync-user-roles")
async def sync_user_roles(
    firebase_uid: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Sync user roles from database to Firestore.
    Only admins can sync other users' roles.
    """
    try:
        # Check if current user is admin
        if not current_user.get('is_admin'):
            raise HTTPException(status_code=403, detail="Only admins can sync user roles")
        
        # Service handles all business logic
        result = await auth_optimized_service.sync_user_roles(firebase_uid)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user roles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to sync user roles: {str(e)}")
