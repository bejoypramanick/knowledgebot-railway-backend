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
from shared.db import railway_db
from shared.firebase_auth import verify_firebase_token, get_user_by_uid, init_firebase_auth
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
        
        # Get user from PostgreSQL (if exists)
        user_data = None
        if railway_db and hasattr(railway_db, '_pool') and railway_db._pool:
            async with railway_db.acquire() as conn:
                user_row = await conn.fetchrow(
                    """
                    SELECT id, firebase_uid, email, display_name, role, email_verified, photo_url, disabled
                    FROM users
                    WHERE firebase_uid = $1
                    """,
                    decoded_token.get('uid')
                )
                
                if user_row:
                    user_data = {
                        'id': str(user_row['id']),
                        'firebase_uid': user_row['firebase_uid'],
                        'email': user_row['email'],
                        'display_name': user_row['display_name'],
                        'role': user_row['role'],
                        'email_verified': user_row['email_verified'],
                        'photo_url': user_row['photo_url'],
                        'disabled': user_row['disabled']
                    }
        
        return TokenVerificationResponse(
            valid=True,
            user=user_data or {
                'firebase_uid': decoded_token.get('uid'),
                'email': decoded_token.get('email'),
                'email_verified': decoded_token.get('email_verified', False)
            }
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
    Sync Firebase Auth user to PostgreSQL.
    Called after user signs up or logs in.
    """
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        firebase_uid = user.get('uid')
        email = user.get('email')
        
        if not firebase_uid or not email:
            raise HTTPException(status_code=400, detail="Missing uid or email in token")
        
        async with railway_db.acquire() as conn:
            # Check if user exists
            existing = await conn.fetchrow(
                "SELECT id, role FROM users WHERE firebase_uid = $1",
                firebase_uid
            )
            
            if existing:
                # Update existing user
                await conn.execute(
                    """
                    UPDATE users 
                    SET email = $1, 
                        display_name = $2,
                        email_verified = $3,
                        photo_url = $4,
                        updated_at = NOW()
                    WHERE firebase_uid = $5
                    """,
                    email,
                    user.get('name'),
                    user.get('email_verified', False),
                    user.get('picture'),
                    firebase_uid
                )
                logger.info(f"Updated user {firebase_uid} in database")
            else:
                # Create new user (default role: 'user')
                await conn.execute(
                    """
                    INSERT INTO users (firebase_uid, email, display_name, email_verified, photo_url, role)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    firebase_uid,
                    email,
                    user.get('name'),
                    user.get('email_verified', False),
                    user.get('picture'),
                    'user'  # Default role
                )
                logger.info(f"Created new user {firebase_uid} in database")
        
        return {"success": True, "message": "User synced successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user: {e}")
        raise HTTPException(status_code=500, detail=f"Error syncing user: {str(e)}")


@router.get("/me")
async def get_current_user_info(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get current authenticated user information from PostgreSQL.
    """
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        firebase_uid = user.get('uid')
        
        async with railway_db.acquire() as conn:
            user_row = await conn.fetchrow(
                """
                SELECT id, firebase_uid, email, display_name, role, email_verified, photo_url, disabled, created_at
                FROM users
                WHERE firebase_uid = $1
                """,
                firebase_uid
            )
            
            if not user_row:
                # Return Firebase Auth data if not in PostgreSQL yet
                return {
                    "firebase_uid": firebase_uid,
                    "email": user.get('email'),
                    "email_verified": user.get('email_verified', False),
                    "role": "user"  # Default
                }
            
            return {
                "id": str(user_row['id']),
                "firebase_uid": user_row['firebase_uid'],
                "email": user_row['email'],
                "display_name": user_row['display_name'],
                "role": user_row['role'],
                "email_verified": user_row['email_verified'],
                "photo_url": user_row['photo_url'],
                "disabled": user_row['disabled'],
                "created_at": user_row['created_at'].isoformat() if user_row['created_at'] else None
            }
            
    except Exception as e:
        logger.error(f"Error getting user info: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user info: {str(e)}")

