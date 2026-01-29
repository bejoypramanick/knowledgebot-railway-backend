"""
Notifications Endpoints
Handles notification history, read/unread status, and preferences.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from configuration.core.logging_config import get_railway_logger

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
    request: Request,
    notification: NotificationCreate
):
    """Create a new notification."""
    try:
        service = NotificationsService()
        result = await service.create_notification(
            title=notification.title,
            message=notification.message,
            type=notification.type,
            metadata=notification.metadata,
            user_email=request.headers.get("X-User-Email", "")
        )
        return result
    except Exception as e:
        logger.error(f"Error creating notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating notification: {str(e)}")


@router.get("", response_model=dict)
async def get_notifications(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    unread_only: bool = Query(False),
):
    """Get notifications for the current user."""
    try:
        service = NotificationsService()
        result = await service.get_notifications(
            user_email=request.headers.get("X-User-Email", ""),
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
    request: Request,
    notification_ids: List[str],
):
    """Mark notifications as read."""
    try:
        service = NotificationsService()
        result = await service.mark_notifications_read(
            notification_ids=notification_ids,
            user_email=request.headers.get("X-User-Email", "")
        )
        return result
    except Exception as e:
        logger.error(f"Error marking notifications as read: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error marking notifications as read: {str(e)}")


@router.put("/mark-all-read", response_model=dict)
async def mark_all_notifications_read(
    request: Request,
):
    """Mark all notifications as read for the current user."""
    try:
        service = NotificationsService()
        result = await service.mark_all_notifications_read(
            user_email=request.headers.get("X-User-Email", "")
        )
        return result
    except Exception as e:
        logger.error(f"Error marking all notifications as read: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error marking all notifications as read: {str(e)}")


@router.delete("/{notification_id}", response_model=dict)
async def delete_notification(
    request: Request,
    notification_id: str,
):
    """Delete a notification."""
    try:
        service = NotificationsService()
        result = await service.delete_notification(
            notification_id=notification_id,
            user_email=request.headers.get("X-User-Email", "")
        )
        return result
    except Exception as e:
        logger.error(f"Error deleting notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error deleting notification: {str(e)}")
