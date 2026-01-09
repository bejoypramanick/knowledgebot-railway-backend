"""
Notifications Endpoints
Handles notification history, read/unread status, and preferences.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import List, Optional
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationCreate(BaseModel):
    title: str
    message: str
    type: str = 'info'  # 'info', 'success', 'warning', 'error'
    metadata: Optional[dict] = None


class NotificationResponse(BaseModel):
    id: str
    title: str
    message: str
    type: str
    is_read: bool
    read_at: Optional[str] = None
    metadata: Optional[dict] = None
    created_at: str


class NotificationListResponse(BaseModel):
    notifications: List[NotificationResponse]
    total: int
    unread_count: int


class MarkReadRequest(BaseModel):
    notification_ids: List[str]


@router.post("", response_model=NotificationResponse)
async def create_notification(
    notification: NotificationCreate,
    user_email: Optional[str] = Query(None, description="User email (optional, defaults to current user)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Create a notification for a user.
    If user_email is not provided, uses the current authenticated user's email.
    """
    try:
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            # Use provided email or current user's email
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Validate notification type
            if notification.type not in ['info', 'success', 'warning', 'error']:
                notification.type = 'info'
            
            # Insert notification
            notification_id = await conn.fetchval(
                """
                INSERT INTO notifications (user_email, title, message, type, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id
                """,
                target_email,
                notification.title,
                notification.message,
                notification.type,
                notification.metadata or {}
            )
            
            # Fetch the created notification
            result = await conn.fetchrow(
                """
                SELECT id, title, message, type, is_read, read_at, metadata, created_at
                FROM notifications
                WHERE id = $1
                """,
                notification_id
            )
            
            logger.info(f"Created notification {notification_id} for {target_email}")
            
            return NotificationResponse(
                id=str(result['id']),
                title=result['title'],
                message=result['message'],
                type=result['type'],
                is_read=result['is_read'],
                read_at=result['read_at'].isoformat() if result['read_at'] else None,
                metadata=result['metadata'] if result['metadata'] else None,
                created_at=result['created_at'].isoformat()
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating notification: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    user_email: Optional[str] = Query(None, description="User email (optional, defaults to current user)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get notifications for a user.
    """
    try:
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Build query
            where_clause = "WHERE user_email = $1"
            params = [target_email]
            param_index = 2
            
            if unread_only:
                where_clause += f" AND is_read = FALSE"
            
            # Get notifications
            notifications = await conn.fetch(
                f"""
                SELECT id, title, message, type, is_read, read_at, metadata, created_at
                FROM notifications
                {where_clause}
                ORDER BY created_at DESC
                LIMIT ${param_index} OFFSET ${param_index + 1}
                """,
                *params, limit, offset
            )
            
            # Get total count
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM notifications {where_clause}",
                *params
            )
            
            # Get unread count
            unread_count = await conn.fetchval(
                "SELECT COUNT(*) FROM notifications WHERE user_email = $1 AND is_read = FALSE",
                target_email
            )
            
            return NotificationListResponse(
                notifications=[
                    NotificationResponse(
                        id=str(n['id']),
                        title=n['title'],
                        message=n['message'],
                        type=n['type'],
                        is_read=n['is_read'],
                        read_at=n['read_at'].isoformat() if n['read_at'] else None,
                        metadata=n['metadata'] if n['metadata'] else None,
                        created_at=n['created_at'].isoformat()
                    )
                    for n in notifications
                ],
                total=total,
                unread_count=unread_count
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/mark-read", response_model=dict)
async def mark_notifications_read(
    request: MarkReadRequest,
    user_email: Optional[str] = Query(None, description="User email (optional, defaults to current user)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Mark one or more notifications as read.
    """
    try:
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Mark notifications as read
            updated = await conn.execute(
                """
                UPDATE notifications
                SET is_read = TRUE, read_at = CURRENT_TIMESTAMP
                WHERE id = ANY($1::uuid[]) AND user_email = $2
                """,
                request.notification_ids,
                target_email
            )
            
            logger.info(f"Marked {len(request.notification_ids)} notifications as read for {target_email}")
            
            return {
                'success': True,
                'updated_count': updated.split()[-1] if updated else 0
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notifications as read: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/mark-all-read", response_model=dict)
async def mark_all_notifications_read(
    user_email: Optional[str] = Query(None, description="User email (optional, defaults to current user)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Mark all notifications as read for a user.
    """
    try:
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Mark all notifications as read
            updated = await conn.execute(
                """
                UPDATE notifications
                SET is_read = TRUE, read_at = CURRENT_TIMESTAMP
                WHERE user_email = $1 AND is_read = FALSE
                """,
                target_email
            )
            
            logger.info(f"Marked all notifications as read for {target_email}")
            
            return {
                'success': True,
                'updated_count': updated.split()[-1] if updated else 0
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.delete("/{notification_id}", response_model=dict)
async def delete_notification(
    notification_id: str,
    user_email: Optional[str] = Query(None, description="User email (optional, defaults to current user)"),
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a notification.
    """
    try:
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Delete notification
            deleted = await conn.execute(
                """
                DELETE FROM notifications
                WHERE id = $1 AND user_email = $2
                """,
                notification_id,
                target_email
            )
            
            if deleted == "DELETE 0":
                raise HTTPException(status_code=404, detail="Notification not found")
            
            logger.info(f"Deleted notification {notification_id} for {target_email}")
            
            return {'success': True, 'message': 'Notification deleted'}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting notification: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
