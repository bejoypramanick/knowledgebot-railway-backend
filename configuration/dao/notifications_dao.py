"""
Notifications Data Access Object for Configuration Service
Handles database operations for user notifications
"""
from typing import Dict, List, Any, Optional

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("notifications_dao", "configuration")

class NotificationsDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_settings(self) -> Dict[str, Any]:
        """Get notification settings."""
        query = """
            SELECT email_notifications, push_notifications, in_app_notifications, 
                   notification_frequency, quiet_hours_enabled, quiet_hours_start, quiet_hours_end
            FROM notification_settings
            WHERE id = 1
        """
        
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return dict(result) if result else {}
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return {}

    async def update_settings(self, settings: Dict[str, Any], user_email: str) -> Dict[str, Any]:
        """Update notification settings."""
        try:
            async with get_db_connection() as conn:
                query = """
                    INSERT INTO notification_settings 
                    (id, email_notifications, push_notifications, in_app_notifications, 
                     notification_frequency, quiet_hours_enabled, quiet_hours_start, quiet_hours_end, 
                     updated_by, updated_at)
                    VALUES (1, $1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        email_notifications = EXCLUDED.email_notifications,
                        push_notifications = EXCLUDED.push_notifications,
                        in_app_notifications = EXCLUDED.in_app_notifications,
                        notification_frequency = EXCLUDED.notification_frequency,
                        quiet_hours_enabled = EXCLUDED.quiet_hours_enabled,
                        quiet_hours_start = EXCLUDED.quiet_hours_start,
                        quiet_hours_end = EXCLUDED.quiet_hours_end,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = EXCLUDED.updated_at
                """
                params = [
                    settings.get('email_notifications', False),
                    settings.get('push_notifications', False),
                    settings.get('in_app_notifications', False),
                    settings.get('notification_frequency', 'immediate'),
                    settings.get('quiet_hours_enabled', False),
                    settings.get('quiet_hours_start', '22:00'),
                    settings.get('quiet_hours_end', '08:00'),
                    user_email
                ]
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
                return {"success": True}
        except Exception as e:
            logger.log_db_query("update_settings", {"settings": settings, "user_email": user_email}, error=e)
            raise

    async def create_notification(self, title: str, message: str, notification_type: str = 'info', user_email: str = None) -> str:
        """Create a new notification."""
        try:
            async with get_db_connection() as conn:
                query = """
                    INSERT INTO notifications (title, message, notification_type, user_email, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    RETURNING id
                """
                params = [title, message, notification_type, user_email]
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
                        SELECT id, title, message, notification_type, user_email, created_at, read_at,
                               CASE WHEN read_at IS NULL THEN false ELSE true END as read
                        FROM notifications
                        WHERE user_email = $1 AND read_at IS NULL
                        ORDER BY created_at DESC
                        LIMIT $2 OFFSET $3
                    """
                else:
                    query = """
                        SELECT id, title, message, notification_type, user_email, created_at, read_at,
                               CASE WHEN read_at IS NULL THEN false ELSE true END as read
                        FROM notifications
                        WHERE user_email = $1
                        ORDER BY created_at DESC
                        LIMIT $2 OFFSET $3
                    """
                params = [user_email, limit, offset]
                rows = await conn.fetch(query, *params)
                logger.log_db_query(query, params, f"{len(rows)} rows")

                # Convert to list of dicts
                notifications = []
                for row in rows:
                    notifications.append({
                        "id": str(row["id"]),
                        "title": row["title"],
                        "message": row["message"],
                        "type": row["notification_type"],
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
                # Convert string IDs to integers if needed
                int_ids = [int(nid) if isinstance(nid, str) else nid for nid in notification_ids]
                query = """
                    UPDATE notifications
                    SET read_at = NOW()
                    WHERE id = ANY($1) AND read_at IS NULL
                """
                result = await conn.execute(query, int_ids)
                # Extract count from result string like "UPDATE 3"
                count = int(result.split()[-1]) if result else 0
                logger.log_db_query(query, {"ids": int_ids}, f"Updated {count} rows")
                return count
        except Exception as e:
            logger.log_db_query("mark_as_read", {"notification_ids": notification_ids}, error=e)
            raise

    async def mark_all_as_read(self, user_email: str) -> int:
        """Mark all notifications as read for a user."""
        try:
            async with get_db_connection() as conn:
                query = """
                    UPDATE notifications
                    SET read_at = NOW()
                    WHERE user_email = $1 AND read_at IS NULL
                """
                result = await conn.execute(query, user_email)
                # Extract count from result string like "UPDATE 5"
                count = int(result.split()[-1]) if result else 0
                logger.log_db_query(query, {"user_email": user_email}, f"Updated {count} rows")
                return count
        except Exception as e:
            logger.log_db_query("mark_all_as_read", {"user_email": user_email}, error=e)
            raise
