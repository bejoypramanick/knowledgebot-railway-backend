"""
Notifications Endpoints
Handles notification history, read/unread status, and preferences.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from configuration.core.logging_config import get_railway_logger

# Placeholder for authentication since it's handled at API Gateway level
def get_current_user():
    """Placeholder function - authentication is handled at API Gateway level"""
    return {"email": "system@example.com"}

from ..service.notifications_service import NotificationsService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


class NotificationCreate(BaseModel):
    title: str
    message: str
    type: str = "info"
    metadata: Optional[dict] = None


class NotificationResponse(BaseModel):
    success: bool
    notification_id: str


class NotificationListResponse(BaseModel):
    notifications: List[dict]
    total: int
    unread_count: int


@router.post("", response_model=NotificationResponse)
async def create_notification(
    notification: NotificationCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new notification."""
    try:
        service = NotificationsService()
        result = await service.create_notification(
            title=notification.title,
            message=notification.message,
            type=notification.type,
            metadata=notification.metadata,
            user_email=current_user.get('email')
        )
        return result
    except Exception as e:
        logger.error(f"Error creating notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating notification: {str(e)}")


@router.get("", response_model=NotificationListResponse)
async def get_notifications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
    current_user: dict = Depends(get_current_user)
):
    """Get notifications for the current user."""
    try:
        service = NotificationsService()
        result = await service.get_notifications(
            user_email=current_user.get('email'),
            limit=limit,
            offset=offset,
            unread_only=unreadOnly
        )
        return result
    except Exception as e:
        logger.error(f"Error fetching notifications: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching notifications: {str(e)}")


@router.put("/mark-read", response_model=dict)
async def mark_notifications_read(
    notification_ids: List[str],
    current_user: dict = Depends(get_current_user)
):
    """Mark notifications as read."""
    try:
        service = NotificationsService()
        result = await service.mark_notifications_read(
            notification_ids=notification_ids,
            user_email=current_user.get('email')
        )
        return result
    except Exception as e:
        logger.error(f"Error marking notifications as read: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error marking notifications as read: {str(e)}")


@router.put("/mark-all-read", response_model=dict)
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user)
):
    """Mark all notifications as read for the current user."""
    try:
        service = NotificationsService()
        result = await service.mark_all_notifications_read(
            user_email=current_user.get('email')
        )
        return result
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error marking all notifications as read: {str(e)}")


@router.delete("/{notification_id}", response_model=dict)
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a notification."""
    try:
        service = NotificationsService()
        result = await service.delete_notification(
            notification_id=notification_id,
            user_email=current_user.get('email')
        )
        return result
    except Exception as e:
        logger.error(f"Error deleting notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting notification: {str(e)}")
