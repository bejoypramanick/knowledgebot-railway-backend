"""
Authentication Endpoints
Handles Firebase Auth token verification and user management.
User data stored in Firestore, roles determined from PostgreSQL.
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
from shared.db import railway_db

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
        
        # Check database for exact roles (source of truth)
        try:
            if railway_db and hasattr(railway_db, '_pool') and railway_db._pool is not None and email:
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
            
        except Exception as role_error:
            logger.warning(f"Error determining user roles from database in verify-token: {role_error}")
        
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
    Determines user role from database (admin, human_agent, or user).
    """
    try:
        firebase_uid = user.get('uid')
        email = user.get('email')
        
        if not firebase_uid or not email:
            raise HTTPException(status_code=400, detail="Missing uid or email in token")
        
        # Get existing user from Firestore
        existing_user = get_user_from_firestore(firebase_uid)
        
        # Determine all user roles from database (user can have multiple roles)
        user_roles = []  # List of all roles user has
        primary_role = 'user'  # Default primary role
        is_admin = False
        is_human_agent = False
        
        try:
            # Import here to avoid circular dependency
            from shared.db import railway_db
            
            if railway_db and hasattr(railway_db, '_pool') and railway_db._pool is not None:
                async with railway_db.acquire() as conn:
                    # Check if user is an admin
                    admin = await conn.fetchrow(
                        "SELECT email FROM admins WHERE email = $1 AND status = 'confirmed'",
                        email
                    )
                    if admin:
                        user_roles.append('admin')
                        is_admin = True
                        primary_role = 'admin'  # Admin takes precedence
                    
                    # Check if user is a human agent (can be both admin and agent)
                    agent = await conn.fetchrow(
                        "SELECT email FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')",
                        email
                    )
                    if agent:
                        user_roles.append('human_agent')
                        is_human_agent = True
                        if primary_role == 'user':
                            primary_role = 'human_agent'
        except Exception as role_error:
            logger.warning(f"Error determining user roles from database: {role_error}, defaulting to 'user'")
        
        # Always include 'user' role as fallback
        if 'user' not in user_roles:
            user_roles.append('user')
        
        # If no roles found, default to user
        if not user_roles:
            user_roles = ['user']
            primary_role = 'user'
        
        # Preserve role if user already exists in Firestore (unless database says otherwise)
        if existing_user and 'role' in existing_user:
            # Only update if database has a different primary role (database is source of truth)
            if primary_role != existing_user.get('role'):
                logger.info(f"Updating user role from {existing_user.get('role')} to {primary_role} based on database")
            else:
                primary_role = existing_user.get('role')
        
        # Prepare user data
        user_data = {
            'email': email,
            'display_name': user.get('name'),
            'email_verified': user.get('email_verified', False),
            'photo_url': user.get('picture'),
            'role': primary_role,  # Primary role for backward compatibility
            'primary_role': primary_role,
            'roles': user_roles,  # All available roles
            'is_admin': is_admin,
            'is_human_agent': is_human_agent,
        }
        
        # Save to Firestore
        success = save_user_to_firestore(firebase_uid, user_data)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to save user to Firestore")
        
        logger.info(f"User {firebase_uid} synced to Firestore with roles: {user_roles}, primary: {primary_role}")
        return {
            "success": True, 
            "message": "User synced successfully", 
            "role": primary_role,  # For backward compatibility
            "primary_role": primary_role,
            "roles": user_roles,  # All available roles
            "is_admin": is_admin,
            "is_human_agent": is_human_agent
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user: {e}")
        raise HTTPException(status_code=500, detail=f"Error syncing user: {str(e)}")


@router.get("/me")
async def get_current_user_info(user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get current authenticated user information from Firestore.
    Returns all roles for the user (admin, human_agent, user) so they can toggle between them.
    """
    try:
        firebase_uid = user.get('uid')
        email = user.get('email')
        
        # Get user from Firestore
        user_data = get_user_from_firestore(firebase_uid)
        
        # Get all roles from database (source of truth)
        user_roles = []  # List of all roles user has
        primary_role = 'user'  # Default primary role
        
        try:
            if railway_db and hasattr(railway_db, '_pool') and railway_db._pool is not None and email:
                async with railway_db.acquire() as conn:
                    # Check if user is an admin
                    admin = await conn.fetchrow(
                        "SELECT email FROM admins WHERE email = $1 AND status = 'confirmed'",
                        email
                    )
                    if admin:
                        user_roles.append('admin')
                        primary_role = 'admin'  # Admin takes precedence
                    
                    # Check if user is a human agent (recognize both confirmed and pending)
                    agent = await conn.fetchrow(
                        "SELECT email FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')",
                        email
                    )
                    if agent:
                        user_roles.append('human_agent')
                        if primary_role == 'user':
                            primary_role = 'human_agent'
        except Exception as role_error:
            logger.warning(f"Error determining user roles from database: {role_error}")
            # Fallback to Firestore role if database check fails
            if user_data and 'role' in user_data:
                primary_role = user_data.get('role')
                user_roles = [primary_role]
        
        # Always include 'user' role as fallback
        if 'user' not in user_roles:
            user_roles.append('user')
        
        # If no roles found, default to user
        if not user_roles:
            user_roles = ['user']
            primary_role = 'user'
        
        if not user_data:
            # Return basic Firebase Auth data if not in Firestore yet
            return {
                "uid": firebase_uid,
                "email": email,
                "email_verified": user.get('email_verified', False),
                "display_name": user.get('name'),
                "photo_url": user.get('picture'),
                "role": primary_role,
                "roles": user_roles,  # All available roles
                "primary_role": primary_role
            }
        
        # Convert Firestore timestamps to ISO format
        result = {
            "uid": user_data.get('uid', firebase_uid),
            "email": user_data.get('email') or email,
            "display_name": user_data.get('display_name'),
            "role": primary_role,  # Primary role (for backward compatibility)
            "roles": user_roles,  # All available roles
            "primary_role": primary_role,
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
