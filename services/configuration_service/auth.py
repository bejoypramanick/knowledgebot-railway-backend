"""
Authentication Endpoints
Handles Firebase Auth token verification and user management.
All user data stored in PostgreSQL (not Firestore).
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import logging
import sys
from pathlib import Path

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class TokenVerificationRequest(BaseModel):
    id_token: str


class TokenVerificationResponse(BaseModel):
    valid: bool
    user: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


@router.post("/verify-token", response_model=TokenVerificationResponse)
async def verify_token(request: TokenVerificationRequest):
    """
    Verify Firebase Auth token and return user information.
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
        user_data = get_user_from_firestore(uid)
        
        # If user doesn't exist in Firestore, return Firebase Auth data
        if not user_data:
            user_data = {
                'uid': uid,
                'email': decoded_token.get('email'),
                'email_verified': decoded_token.get('email_verified', False),
                'display_name': decoded_token.get('name'),
                'photo_url': decoded_token.get('picture'),
                'role': 'user'  # Default role
            }
        
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


@router.post("/sync-user")
async def sync_user(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Sync Firebase Auth user to Firestore.
    Called after user signs up or logs in.
    """
    try:
        firebase_uid = user.get('uid')
        email = user.get('email')
        
        if not firebase_uid or not email:
            raise HTTPException(status_code=400, detail="Missing uid or email in token")
        
        # Get existing user from Firestore
        existing_user = get_user_from_firestore(firebase_uid)
        
        # Prepare user data
        user_data = {
            'email': email,
            'display_name': user.get('name'),
            'email_verified': user.get('email_verified', False),
            'photo_url': user.get('picture'),
        }
        
        # Preserve role if user already exists
        if existing_user and 'role' in existing_user:
            user_data['role'] = existing_user['role']
        else:
            user_data['role'] = 'user'  # Default role for new users
        
        # Save to Firestore
        success = save_user_to_firestore(firebase_uid, user_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save user to Firestore")
        
        logger.info(f"User {firebase_uid} synced to Firestore")
        return {"success": True, "message": "User synced successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user: {e}")
        raise HTTPException(status_code=500, detail=f"Error syncing user: {str(e)}")


@router.get("/me")
async def get_current_user_info(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get current authenticated user information from Firestore.
    """
    try:
        firebase_uid = user.get('uid')
        
        # Get user from Firestore
        user_data = get_user_from_firestore(firebase_uid)
        
        if not user_data:
            # Return Firebase Auth data if not in Firestore yet
            return {
                "uid": firebase_uid,
                "email": user.get('email'),
                "email_verified": user.get('email_verified', False),
                "display_name": user.get('name'),
                "photo_url": user.get('picture'),
                "role": "user"  # Default
            }
        
        # Convert Firestore timestamps to ISO format
        result = {
            "uid": user_data.get('uid', firebase_uid),
            "email": user_data.get('email'),
            "display_name": user_data.get('display_name'),
            "role": user_data.get('role', 'user'),
            "email_verified": user_data.get('email_verified', False),
            "photo_url": user_data.get('photo_url'),
        }
        
        # Handle Firestore timestamps
        if 'created_at' in user_data and hasattr(user_data['created_at'], 'isoformat'):
            result['created_at'] = user_data['created_at'].isoformat()
        elif 'created_at' in user_data:
            result['created_at'] = str(user_data['created_at'])
            
        if 'updated_at' in user_data and hasattr(user_data['updated_at'], 'isoformat'):
            result['updated_at'] = user_data['updated_at'].isoformat()
        elif 'updated_at' in user_data:
            result['updated_at'] = str(user_data['updated_at'])
        
        return result
            
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user info: {str(e)}")

