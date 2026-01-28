from shared.logging_config import get_railway_logger
import logging
from typing import Optional, Dict, Any, List
from shared.db import get_db_connection

logger = get_railway_logger(__name__)

class NotificationsDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_notification(self, user_email: str, title: str, message: str, 
                                notification_type: str, metadata: Optional[Dict] = None) -> str:
        """Create a new notification."""
        async with get_db_connection() as conn:
            return await conn.fetchval(
                """
                INSERT INTO notifications (user_email, title, message, type, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING id::text
                """,
                user_email, title, message, notification_type, metadata
            )

    async def get_notification_by_id(self, notification_id: str) -> Optional[Dict[str, Any]]:
        """Get notification by ID."""
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                """
                SELECT id, title, message, type, is_read, read_at, metadata, created_at
                FROM notifications
                WHERE id = $1
                """,
                notification_id
            )

    async def get_notifications(self, user_email: str, is_read: Optional[bool] = None, 
                               limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get notifications for a user with optional filtering."""
        where_clause = "WHERE user_email = $1"
        params = [user_email]
        
        if is_read is not None:
            where_clause += f" AND is_read = ${len(params) + 1}"
            params.append(is_read)
        
        query = f"""
            SELECT id, title, message, type, is_read, read_at, metadata, created_at
            FROM notifications {where_clause}
            ORDER BY created_at DESC
            LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """
        params.extend([limit, offset])
        
        async with get_db_connection() as conn:
            return await conn.fetch(query, *params)

    async def get_notifications_count(self, user_email: str, is_read: Optional[bool] = None) -> int:
        """Get total count of notifications for a user."""
        where_clause = "WHERE user_email = $1"
        params = [user_email]
        
        if is_read is not None:
            where_clause += f" AND is_read = ${len(params) + 1}"
            params.append(is_read)
        
        async with get_db_connection() as conn:
            return await conn.fetchval(f"SELECT COUNT(*) FROM notifications {where_clause}", *params)

    async def get_unread_count(self, user_email: str) -> int:
        """Get unread notifications count for a user."""
        async with get_db_connection() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM notifications WHERE user_email = $1 AND is_read = FALSE",
                user_email
            )

    async def mark_notification_read(self, notification_id: str, user_email: str) -> int:
        """Mark a specific notification as read."""
        async with get_db_connection() as conn:
            return await conn.execute(
                """
                UPDATE notifications
                SET is_read = TRUE, read_at = CURRENT_TIMESTAMP
                WHERE id = $1 AND user_email = $2 AND is_read = FALSE
                """,
                notification_id, user_email
            )

    async def mark_all_notifications_read(self, user_email: str) -> int:
        """Mark all notifications as read for a user."""
        async with get_db_connection() as conn:
            return await conn.execute(
                """
                UPDATE notifications
                SET is_read = TRUE, read_at = CURRENT_TIMESTAMP
                WHERE user_email = $1 AND is_read = FALSE
                """,
                user_email
            )

    async def mark_multiple_notifications_read(self, notification_ids: List[str], user_email: str) -> int:
        """Mark multiple notifications as read for a user."""
        async with get_db_connection() as conn:
            return await conn.execute(
                """
                UPDATE notifications
                SET is_read = TRUE, read_at = CURRENT_TIMESTAMP
                WHERE id = ANY($1::uuid[]) AND user_email = $2 AND is_read = FALSE
                """,
                notification_ids, user_email
            )

    async def delete_notification(self, notification_id: str, user_email: str) -> int:
        """Delete a specific notification."""
        async with get_db_connection() as conn:
            return await conn.execute(
                "DELETE FROM notifications WHERE id = $1 AND user_email = $2",
                notification_id, user_email
            )
