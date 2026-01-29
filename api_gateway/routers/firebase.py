"""
Firebase Token Verification Endpoints
Provides endpoints for token verification and user lookup.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api_gateway.core.firebase_auth import verify_firebase_token
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/firebase", tags=["firebase"])


class TokenRequest(BaseModel):
    token: str


@router.post("/verify-token")
async def verify_token(request: TokenRequest):
    """Verify Firebase token and return user information."""
    try:
        user_data = verify_firebase_token(request.token)
        
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "success": True,
            "user": user_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        raise HTTPException(status_code=500, detail=f"Error verifying token: {str(e)}")


@router.get("/user/{uid}")
async def get_user_by_uid(uid: str):
    """Get user information by Firebase UID."""
    try:
        from api_gateway.core.firebase_auth import get_user_from_firestore
        user_data = get_user_from_firestore(uid)
        
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "success": True,
            "user": user_data
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user by UID {uid}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")
