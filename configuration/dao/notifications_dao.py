"""
Notifications Data Access Object for Configuration Service
Handles database operations for user notifications
"""
from typing import Dict, List, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("notifications_dao", "configuration")

class NotificationsDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_settings(self) -> Dict[str, Any]:
        """Get notification settings (defaults since notification_settings table is being removed)."""
        return {
            "email_notifications": False,
            "push_notifications": False,
            "in_app_notifications": True,
            "notification_frequency": "immediate",
            "quiet_hours_enabled": False,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "08:00"
        }

    async def update_settings(self, settings: Dict[str, Any], user_email: str) -> Dict[str, Any]:
        """Update notification settings."""
        logger.info(f"Notification settings update requested for {user_email}: {settings}")
        return settings

    async def create_notification(self, title: str, message: str, notification_type: str = 'info', user_email: str = None) -> str:
        """Create a new notification."""
        query = """
            INSERT INTO notifications (title, message, type, user_email, created_at, updated_at)
            VALUES ($1, $2, $3, $4, NOW(), NOW())
            RETURNING id
        """
        params = [title, message, notification_type, user_email]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_notifications(self, user_email: str, limit: int = 50, offset: int = 0, unread_only: bool = False) -> List[Dict[str, Any]]:
        """Get notifications for a user with pagination."""
        try:
            async with get_db_connection() as conn:
                if unread_only:
                    query = """
                        SELECT id, title, message, type, user_email, created_at, read_at,
                                CASE WHEN read_at IS NULL THEN false ELSE true END as read
                        FROM notifications
                        WHERE user_email = $1 AND read_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT $2 OFFSET $3
                    """
                else:
                    query = """
                        SELECT id, title, message, type, user_email, created_at, read_at,
                                CASE WHEN read_at IS NULL THEN false ELSE true END as read
                        FROM notifications
                        WHERE user_email = $1
                        ORDER BY created_at DESC
                        LIMIT $2 OFFSET $3
                    """
                params = [user_email, limit, offset]
                logger.log_db_operation(query, params)
                rows = await conn.fetch(query, *params)
                logger.log_db_query(query, params, rows)

                notifications = []
                for row in rows:
                    notifications.append({
                        "id": str(row["id"]),
                        "title": row["title"],
                        "message": row["message"],
                        "type": row["type"],
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                        "read": row["read"]
                    })
                return notifications
        except Exception as e:
            logger.log_db_query("get_notifications", {"user_email": user_email}, error=e)
            raise

    async def mark_as_read(self, notification_ids: List[str]) -> int:
        """Mark specific notifications as read."""
        try:
            if not notification_ids:
                return 0
            async with get_db_connection() as conn:
                int_ids = [int(nid) if isinstance(nid, str) else nid for nid in notification_ids]
                query = """
                    UPDATE notifications
                    SET read_at = NOW(), updated_at = NOW()
                    WHERE id = ANY($1) AND read_at IS NULL
                """
                logger.log_db_operation(query, int_ids)
                result = await conn.execute(query, int_ids)
                count = int(result.split()[-1]) if result else 0
                logger.log_db_query(query, {"ids": int_ids}, result)
                return count
        except Exception as e:
            logger.log_db_query("mark_as_read", {"notification_ids": notification_ids}, error=e)
            raise

    async def mark_all_as_read(self, user_email: str) -> int:
        """Mark all notifications as read for a user."""
        query = """
            UPDATE notifications
            SET read_at = NOW(), updated_at = NOW()
            WHERE user_email = $1 AND read_at IS NULL
        """
        try:
            logger.log_db_operation(query, user_email)
            async with get_db_connection() as conn:
                result = await conn.execute(query, user_email)
                count = int(result.split()[-1]) if result else 0
                logger.log_db_query(query, {"user_email": user_email}, result)
                return count
        except Exception as e:
            logger.log_db_query(query, {"user_email": user_email}, error=e)
            raise
