"""
Notifications Service Layer
Provides business logic for notifications management operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.notifications_dao import NotificationsDAO

logger = logging.getLogger(__name__)

class NotificationsService:
    """Service layer for notifications management"""
    
    def __init__(self, notifications_dao: NotificationsDAO):
        self.notifications_dao = notifications_dao
    
    async def create_notification(self, title: str, message: str, notification_type: str = 'info', user_email: str = None) -> Dict[str, Any]:
        """Create a notification"""
        try:
            notification_id = await self.notifications_dao.create_notification(title, message, notification_type, user_email)
            logger.info(f"Notification created: {notification_id}")
            return {"success": True, "notification_id": notification_id}
        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            raise
    
    async def get_notifications(self, limit: int = 50, offset: int = 0, unread_only: bool = False, user_email: str = None) -> List[Dict[str, Any]]:
        """Get notifications for a user"""
        try:
            return await self.notifications_dao.get_notifications(limit, offset, unread_only, user_email)
        except Exception as e:
            logger.error(f"Error fetching notifications: {e}")
            raise
    
    async def mark_notification_read(self, notification_id: str) -> bool:
        """Mark notification as read"""
        try:
            await self.notifications_dao.mark_notification_read(notification_id)
            return True
        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            raise
