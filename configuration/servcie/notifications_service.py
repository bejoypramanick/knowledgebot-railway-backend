"""
Notifications Service Layer
Provides business logic for notifications management operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.notifications_dao import NotificationsDAO
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class NotificationsService:
    """Service layer for notifications management"""
    
    @classmethod
    async def create_notification(cls, title: str, message: str, notification_type: str = 'info', user_email: str = None) -> Dict[str, Any]:
        """Create a notification"""
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            try:
                notification_id = await notifications_dao.create_notification(title, message, notification_type, user_email)
                logger.info(f"Notification created: {notification_id}")
                return {"success": True, "notification_id": notification_id}
            except Exception as e:
                logger.error(f"Error creating notification: {e}")
                raise
    
    @classmethod
    async def get_notifications(cls, limit: int = 50, offset: int = 0, unread_only: bool = False, user_email: str = None) -> List[Dict[str, Any]]:
        """Get notifications for a user"""
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            try:
                return await notifications_dao.get_notifications(limit, offset, unread_only, user_email)
            except Exception as e:
                logger.error(f"Error fetching notifications: {e}")
                raise
    
    @classmethod
    async def mark_notification_read(cls, notification_id: str) -> bool:
        """Mark notification as read"""
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            try:
                await notifications_dao.mark_notification_read(notification_id)
                return True
            except Exception as e:
                logger.error(f"Error marking notification as read: {e}")
                raise
