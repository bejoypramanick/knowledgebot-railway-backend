"""
Notifications Service Layer
Provides business logic for notifications management operations
"""
from typing import Any, Dict, List

from configuration.core.logging_config import get_railway_logger

from ..dao.notifications_dao import NotificationsDAO

logger = get_railway_logger(__name__)

class NotificationsService:
    """Service layer for notifications management"""
    
    def __init__(self, notifications_dao: NotificationsDAO):
        self.notifications_dao = notifications_dao
    
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
    
    async def create_notification(self, title: str, message: str, notification_type: str = 'info', user_email: str = None) -> Dict[str, Any]:
        """Create a notification"""
        try:
            notification_id = await self.notifications_dao.create_notification(title, message, notification_type, user_email)
            logger.info(f"Notification created: {notification_id}")
            return {"success": True, "notification_id": notification_id}
        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            raise
