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
                logger.info(f"🔍 [DB QUERY] get_settings: {query.strip()}")
                return dict(result) if result else {}
        except Exception as e:
            logger.error(f"❌ [DB ERROR] get_settings: {e}")
            return {}

    async def update_settings(self, settings: Dict[str, Any], user_email: str) -> Dict[str, Any]:
        """Update notification settings."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
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
                """, 
                    settings.get('email_notifications', False),
                    settings.get('push_notifications', False),
                    settings.get('in_app_notifications', False),
                    settings.get('notification_frequency', 'immediate'),
                    settings.get('quiet_hours_enabled', False),
                    settings.get('quiet_hours_start', '22:00'),
                    settings.get('quiet_hours_end', '08:00'),
                    user_email
                )
                return {"success": True}
        except Exception as e:
            logger.error(f"Error updating notification settings: {e}")
            raise

    async def create_notification(self, title: str, message: str, notification_type: str = 'info', user_email: str = None) -> str:
        """Create a new notification."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval("""
                    INSERT INTO notifications (title, message, notification_type, user_email, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    RETURNING id
                """, title, message, notification_type, user_email)
        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            raise
