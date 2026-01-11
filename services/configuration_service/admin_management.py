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
from shared.db import railway_db
from shared.email_service import create_email_service
from shared.firebase_auth import get_user_from_firestore, save_user_to_firestore, update_user_role_in_firestore
from shared.auth_middleware import get_current_user

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
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        # Verify current user is an admin
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        # Check if current user is an admin
        async with railway_db.acquire() as conn:
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            
            if not is_admin or is_admin == 0:
                raise HTTPException(status_code=403, detail="Only admins can add new admins")
            
            # Create email service
            email_service = create_email_service(conn)
            admins_created = []
            
            for email in request.emails:
                # Check if admin already exists
                existing = await conn.fetchrow(
                    "SELECT id, status, confirmation_token FROM admins WHERE email = $1",
                    email
                )
                
                if existing:
                    if existing['status'] == 'confirmed':
                        logger.info(f"Admin {email} already confirmed, skipping")
                        continue
                    elif existing['status'] == 'pending':
                        # Resend confirmation email
                        token = existing['confirmation_token']
                        if await email_service.send_admin_confirmation_email(email, token, user_email):
                            admins_created.append({
                                "email": email,
                                "status": "pending",
                                "confirmation_token": token
                            })
                        continue
                
                # Create new admin
                token = generate_confirmation_token()
                admin_id = await conn.fetchval(
                    """
                    INSERT INTO admins (email, status, confirmation_token, created_by_email)
                    VALUES ($1, 'pending', $2, $3)
                    RETURNING id::text
                    """,
                    email, token, user_email
                )
                
                # Send confirmation email
                if await email_service.send_admin_confirmation_email(email, token, user_email):
                    admins_created.append({
                        "email": email,
                        "status": "pending",
                        "confirmation_token": token
                    })
                    logger.info(f"Admin confirmation email sent to {email}")
                else:
                    logger.warning(f"Failed to send admin confirmation email to {email}")
            
            return {
                "success": True,
                "message": "Confirmation emails sent to new admins",
                "admins": admins_created
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding admins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding admins: {str(e)}")


@router.post("/admins/confirm", response_model=dict)
async def confirm_admin(request: ConfirmAdminRequest):
    """Confirm admin account via token."""
    try:
        # Use the same database connection pattern as other endpoints
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Find admin by token
            admin = await conn.fetchrow(
                """
                SELECT id, email, status FROM admins 
                WHERE confirmation_token = $1 AND status = 'pending'
                """,
                request.token
            )
            
            if not admin:
                raise HTTPException(status_code=404, detail="Invalid or expired confirmation token")
            
            # Update admin status
            await conn.execute(
                """
                UPDATE admins 
                SET status = 'confirmed',
                    confirmed_at = NOW()
                WHERE id = $1
                """,
                admin['id']
            )
            
            # Note: Admin emails are now managed through the admins table only
            # No need to update chatbot_configuration - configuration endpoint reads from admins table
            
            logger.info(f"Admin {admin['email']} confirmed successfully")
            
            return {
                "success": True,
                "message": "Admin confirmed successfully",
                "admin": {
                    "email": admin['email']
                }
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error confirming admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error confirming admin: {str(e)}")


@router.get("/admins", response_model=dict)
async def list_admins(current_user: dict = Depends(get_current_user)):
    """List all admins. Only admins can view this list."""
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        # Verify current user is an admin
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        async with railway_db.acquire() as conn:
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            
            if not is_admin or is_admin == 0:
                raise HTTPException(status_code=403, detail="Only admins can view admin list")
            
            # Get all admins
            admins = await conn.fetch(
                """
                SELECT email, status, created_at, confirmed_at, created_by_email
                FROM admins
                ORDER BY created_at DESC
                """
            )
            
            return {
                "success": True,
                "admins": [
                    {
                        "email": admin['email'],
                        "status": admin['status'],
                        "created_at": admin['created_at'].isoformat() if admin['created_at'] else None,
                        "confirmed_at": admin['confirmed_at'].isoformat() if admin['confirmed_at'] else None,
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
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        # Verify current user is an admin
        user_email = current_user.get('email')
        if not user_email:
            raise HTTPException(status_code=403, detail="User email not found in token")
        
        async with railway_db.acquire() as conn:
            is_admin = await conn.fetchval(
                "SELECT COUNT(*) FROM admins WHERE email = $1 AND status = 'confirmed'",
                user_email
            )
            
            if not is_admin or is_admin == 0:
                raise HTTPException(status_code=403, detail="Only admins can remove other admins")
            
            # Check if admin exists
            admin = await conn.fetchrow(
                "SELECT id, email, status FROM admins WHERE email = $1",
                email
            )
            
            if not admin:
                raise HTTPException(status_code=404, detail="Admin not found")
            
            # Update admin status
            await conn.execute(
                """
                UPDATE admins 
                SET status = 'removed',
                    removed_at = NOW()
                WHERE email = $1
                """,
                email
            )
            
            # Note: Admin removal is handled by setting status to 'removed' in admins table
            # No need to update chatbot_configuration - configuration endpoint reads from admins table
            
            # Send removal email
            email_service = create_email_service(conn)
            await email_service.send_admin_removal_email(email)
            
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
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        async with railway_db.acquire() as conn:
            # Check if user is an admin
            admin = await conn.fetchrow(
                "SELECT email FROM admins WHERE email = $1 AND status = 'confirmed'",
                email
            )
            if admin:
                return {"role": "admin", "email": email}
            
            # Check if user is a human agent (recognize both confirmed and pending)
            agent = await conn.fetchrow(
                "SELECT email FROM human_agents WHERE email = $1 AND status IN ('confirmed', 'pending')",
                email
            )
            if agent:
                return {"role": "human_agent", "email": email}
            
            # Default to user
            return {"role": "user", "email": email}
    except Exception as e:
        logger.error(f"Error getting user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user role: {str(e)}")

