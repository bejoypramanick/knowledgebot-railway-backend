"""
Notifications Service for Configuration Service
Provides business logic layer for notifications operations
"""
from typing import Any, Dict, List, Optional

from shared.otel_logger import get_otel_logger
from configuration.dao.notifications_dao import NotificationsDAO

logger = get_otel_logger("notifications_service", "configuration")


class NotificationsService:
    """Service layer for notifications operations"""

    def __init__(self, notifications_dao: Optional[NotificationsDAO] = None):
        self._notifications_dao = notifications_dao or NotificationsDAO()

    async def get_all_notifications(self, user_email: str) -> List[Dict[str, Any]]:
        """Get all notifications for a user"""
        try:
            return await self._notifications_dao.get_all_notifications(user_email)
        except Exception as e:
            logger.error(f"Error getting notifications: {e}")
            raise

    async def mark_as_read(self, notification_id: int) -> bool:
        """Mark notification as read"""
        try:
            await self._notifications_dao.mark_as_read(notification_id)
            return True
        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            raise

    async def delete_notification(self, notification_id: int) -> bool:
        """Delete a notification"""
        try:
            await self._notifications_dao.delete_notification(notification_id)
            return True
        except Exception as e:
            logger.error(f"Error deleting notification: {e}")
            raise

    async def create_notification(self, notification_data: Dict[str, Any]) -> int:
        """Create a new notification"""
        try:
            return await self._notifications_dao.create_notification(notification_data)
        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            raise
