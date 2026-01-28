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
from shared.auth_middleware import get_current_user
from ..servcie.notifications_service import NotificationsService

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
        service = NotificationsService()  # Service manages its own DAO
        
        # Use provided email or current user's email
        target_email = user_email or current_user.get('email')
        if not target_email:
            raise HTTPException(status_code=400, detail="User email is required")
        
        # Validate notification type
        if notification.type not in ['info', 'success', 'warning', 'error']:
            notification.type = 'info'
        
        # Create notification
        notification_id = await service.create_notification(
            target_email,
            notification.title,
            notification.message,
            notification.type,
            notification.metadata or {}
        )
        
        # Fetch the created notification
        result = await service.get_notification_by_id(notification_id)
        
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
        notifications_dao = NotificationsDAO()
        service = NotificationsService(notifications_dao)
        
        target_email = user_email or current_user.get('email')
        if not target_email:
            raise HTTPException(status_code=400, detail="User email is required")
        
        # Get notifications
        is_read = None if not unread_only else False
        notifications = await service.get_notifications(limit, offset, unread_only, target_email)
        
        return NotificationListResponse(
            notifications=[
                NotificationResponse(
                    id=str(notification['id']),
                    title=notification['title'],
                    message=notification['message'],
                    type=notification['type'],
                    is_read=notification['is_read'],
                    read_at=notification['read_at'].isoformat() if notification['read_at'] else None,
                    metadata=notification['metadata'] if notification['metadata'] else None,
                    created_at=notification['created_at'].isoformat() if notification['created_at'] else None
                )
                for notification in notifications
            ],
            total=len(notifications),
            unread_count=len([n for n in notifications if not n.get('is_read', False)])
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
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Mark notifications as read
            updated = await notifications_dao.mark_multiple_notifications_read(
                request.notification_ids, target_email
            )
            
            logger.info(f"Marked {len(request.notification_ids)} notifications as read for {target_email}")
            
            return {
                'success': True,
                'updated_count': updated
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
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Mark all notifications as read
            updated = await notifications_dao.mark_all_notifications_read(target_email)
            
            logger.info(f"Marked all notifications as read for {target_email}")
            
            return {
                'success': True,
                'updated_count': updated
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
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            
            target_email = user_email or current_user.get('email')
            if not target_email:
                raise HTTPException(status_code=400, detail="User email is required")
            
            # Delete notification
            deleted = await notifications_dao.delete_notification(notification_id, target_email)
            
            if deleted == 0:
                raise HTTPException(status_code=404, detail="Notification not found")
            
            logger.info(f"Deleted notification {notification_id} for {target_email}")
            
            return {
                'success': True,
                'message': 'Notification deleted successfully'
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting notification: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
