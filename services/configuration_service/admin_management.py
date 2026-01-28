"""
Admin Management Endpoints
Handles admin user creation, verification, and role management.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import secrets
import logging
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.firebase_auth import get_user_from_firestore, save_user_to_firestore, update_user_role_in_firestore
from shared.auth_middleware import get_current_user
from .main import get_db_connection
from .dao.auth_dao import AuthDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-management"])


class AdminRequest(BaseModel):
    emails: List[EmailStr]


class ConfirmAdminRequest(BaseModel):
    token: str


def generate_confirmation_token() -> str:
    """Generate a secure confirmation token."""
    return secrets.token_urlsafe(32)


@router.post("/admins", response_model=dict)
async def add_admins(request: AdminRequest, current_user: dict = Depends(get_current_user)):
    """Add admin users and send confirmation emails. Only existing admins can add new admins."""
    # Verify current user is an admin
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")
    
    try:
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            
            # Check if current user is an admin
            is_admin = await auth_dao.check_admin_exists(user_email)
            
            if not is_admin or is_admin == 0:
                raise HTTPException(status_code=403, detail="Only admins can add new admins")
            
            # Create admins directly without email confirmation
            admins_created = []
            
            for email in request.emails:
                # Check if admin already exists
                existing = await auth_dao.check_admin_exists(email)

                if existing:
                    logger.info(f"Admin {email} already exists, skipping")
                    continue
                
                # Create new admin
                token = generate_confirmation_token()
                admin_id = await auth_dao.create_admin(email, token, user_email)
                
                # Admin created successfully
                admins_created.append({
                    "email": email,
                    "status": "active",
                    "confirmation_token": token
                })
                logger.info(f"Admin {email} created successfully")
            
            return {
                "success": True,
                "message": "Admins created successfully",
                "admins": admins_created
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding admins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding admins: {str(e)}")


# Admin confirmation endpoint removed - admins are now activated immediately


@router.get("/admins", response_model=dict)
async def list_admins(current_user: dict = Depends(get_current_user)):
    """List all admins. Only admins can view this list."""
    # Verify current user is an admin
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")
    
    try:
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            
            # Check if current user is an admin
            is_admin = await auth_dao.check_admin_exists(user_email)
            
            if not is_admin or is_admin == 0:
                raise HTTPException(status_code=403, detail="Only admins can view admin list")
            
            # Get all admins
            admins = await auth_dao.list_all_admins()
            
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
async def remove_admin(email: str, current_user: dict = Depends(get_current_user)):
    """Remove an admin. Only admins can remove other admins."""
    # Verify current user is an admin
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")
    
    try:
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            
            # Check if current user is an admin
            is_admin = await auth_dao.check_admin_exists(user_email)
            
            if not is_admin or is_admin == 0:
                raise HTTPException(status_code=403, detail="Only admins can remove other admins")
            
            # Check if admin exists
            admin = await auth_dao.check_admin_exists(email)
            
            if not admin:
                raise HTTPException(status_code=404, detail="Admin not found")
            
            # Remove admin
            await auth_dao.remove_admin(email)
            
            # Admin removed - no email notification sent
            
            return {
                "success": True,
                "message": "Admin removed successfully"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing admin: {str(e)}")


@router.get("/user-role/{email}", response_model=dict)
async def get_user_role(email: str):
    """Get user role (admin, human_agent, or user) for a given email."""
    try:
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            
            # Check if user is an admin
            admin = await auth_dao.check_admin_exists(email)
            if admin:
                return {"role": "admin", "email": email}
            
            # Check if user is a human agent
            agent = await auth_dao.check_human_agent_exists(email)
            if agent:
                return {"role": "human_agent", "email": email}
            
            # Default to user
            return {"role": "user", "email": email}
    except Exception as e:
        logger.error(f"Error getting user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user role: {str(e)}")

