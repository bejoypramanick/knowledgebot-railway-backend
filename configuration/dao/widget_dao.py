import logging
import json
from typing import Optional, Dict, Any, List
import asyncpg

logger = logging.getLogger(__name__)

class WidgetDAO:
    def __init__(self, connection):
        self.conn = connection

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get main widget configuration."""
        try:
            return await self.conn.fetchrow(
                """
                SELECT
                    display_name, initial_message, auto_show_duration,
                    keep_showing_suggested, theme, primary_color,
                    use_primary_for_header, chat_bubble_color, align_bubble,
                    display_chatbot, profile_picture_url, chat_icon_url,
                    profile_zoom, chat_icon_zoom, profile_position,
                    chat_icon_position, profile_picture_filename,
                    chat_icon_filename, updated_at
                FROM widget_configuration
                WHERE id = 1
                """
            )
        except asyncpg.exceptions.UndefinedColumnError:
            # Fallback for older schema
            return await self.conn.fetchrow(
                """
                SELECT
                    display_name, initial_message, auto_show_duration,
                    keep_showing_suggested, theme, primary_color,
                    use_primary_for_header, chat_bubble_color, align_bubble,
                    display_chatbot, profile_picture_url, chat_icon_url,
                    updated_at
                FROM widget_configuration
                WHERE id = 1
                """
            )

    async def get_suggested_messages(self) -> List[str]:
        """Get suggested messages."""
        rows = await self.conn.fetch(
            """
            SELECT message_text
            FROM widget_suggested_messages
            WHERE widget_config_id = 1 AND is_active = true
            ORDER BY display_order
            """
        )
        return [r["message_text"] for r in rows] if rows else []

    async def clear_suggested_messages(self):
        await self.conn.execute("DELETE FROM widget_suggested_messages WHERE widget_config_id = 1")

    async def add_suggested_message(self, message: str, order: int):
        await self.conn.execute(
            """
            INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active)
            VALUES (1, $1, $2, true)
            """,
            message, order
        )

    async def get_existing_id(self) -> Optional[int]:
        return await self.conn.fetchval("SELECT id FROM widget_configuration LIMIT 1")

    async def update_widget_config(self, record_id: int, updates: Dict[str, Any]):
        columns = list(updates.keys())
        values = list(updates.values())
        
        set_clause = [f"{col} = ${i+1}" for i, col in enumerate(columns)]
        
        query = f"""
            UPDATE widget_configuration
            SET {', '.join(set_clause)}, updated_at = CURRENT_TIMESTAMP
            WHERE id = {record_id}
        """
        await self.conn.execute(query, *values)

    async def insert_widget_config(self, updates: Dict[str, Any]):
        columns = list(updates.keys())
        values = list(updates.values())
        
        placeholders = [f"${i+1}" for i in range(len(columns))]
        
        query = f"""
            INSERT INTO widget_configuration (id, {', '.join(columns)})
            VALUES (1, {', '.join(placeholders)})
        """
        await self.conn.execute(query, *values)
