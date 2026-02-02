"""
Notifications Service Layer
Provides business logic for notifications management operations
"""
from typing import Any, Dict, List

from configuration.core.otel_logger import get_otel_logger

from ..dao.notifications_dao import NotificationsDAO

logger = get_otel_logger("notifications_service", "configuration")

class NotificationsService:
    """Service layer for notifications management"""

    def __init__(self, notifications_dao: NotificationsDAO = None):
        self.notifications_dao = notifications_dao or NotificationsDAO()
    
    async def get_settings(self) -> Dict[str, Any]:
        """Get notification settings"""
        try:
            settings = await self.notifications_dao.get_settings()
            return settings
        except Exception as e:
            logger.error(f"Error getting notification settings: {e}")
            raise
    
    async def update_settings(self, settings: Dict[str, Any], user_email: str) -> Dict[str, Any]:
        """Update notification settings"""
        try:
            result = await self.notifications_dao.update_settings(settings, user_email)
            return {"success": True, "message": "Settings updated successfully", "data": result}
        except Exception as e:
            logger.error(f"Error updating notification settings: {e}")
            raise
    
    async def send_notification(self, notification: Dict[str, Any], user_email: str) -> Dict[str, Any]:
        """Send a notification"""
        try:
            result = await self.create_notification(
                notification.get("title", "Notification"),
                notification.get("message", ""),
                notification.get("type", "info"),
                user_email
            )
            return {"success": True, "message": "Notification sent successfully", "notification_id": result["notification_id"]}
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
            raise
    
    async def create_notification(self, data: Any, user_email: str = None) -> Dict[str, Any]:
        """Create a notification"""
        try:
            if isinstance(data, dict):
                title = data.get("title", "Notification")
                message = data.get("message", "")
                notification_type = data.get("type", "info")
            else:
                title = data
                message = ""
                notification_type = "info"

            notification_id = await self.notifications_dao.create_notification(title, message, notification_type, user_email)
            logger.info(f"Notification created: {notification_id}")
            return {"success": True, "notification_id": notification_id}
        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            raise

    async def get_notifications(self, user_email: str, limit: int = 50, offset: int = 0, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Get notifications for a user with pagination"""
        try:
            return await self.notifications_dao.get_notifications(user_email, limit, offset, unread_only)
        except Exception as e:
            logger.error(f"Error getting notifications: {e}")
            raise

    async def mark_as_read(self, notification_ids: List[str]) -> int:
        """Mark specific notifications as read. Returns count of updated notifications."""
        try:
            count = await self.notifications_dao.mark_as_read(notification_ids)
            return count
        except Exception as e:
            logger.error(f"Error marking notifications as read: {e}")
            raise

    async def mark_all_as_read(self, user_email: str) -> int:
        """Mark all notifications as read for a user. Returns count of updated notifications."""
        try:
            count = await self.notifications_dao.mark_all_as_read(user_email)
            return count
        except Exception as e:
            logger.error(f"Error marking all notifications as read: {e}")
            raise
