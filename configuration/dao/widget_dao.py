import logging
import json
from typing import Optional, Dict, Any, List
import asyncpg
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class WidgetDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get main widget configuration."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow(
                    """
                    SELECT
                        display_name, initial_message, auto_show_duration,
                        keep_showing_suggested, theme, primary_color,
                        use_primary_for_header, chat_bubble_color, align_bubble,
                        display_chatbot, profile_picture_url, chat_icon_url,
                        profile_picture_filename, chat_icon_filename,
                        profile_zoom, chat_icon_zoom, profile_position, chat_icon_position
                    FROM widget_config
                    WHERE id = 1
                    """
                )
        except Exception as e:
            logger.error(f"Error fetching widget config: {e}")
            return None

    async def get_suggested_messages(self) -> List[str]:
        """Get suggested messages for the widget."""
        try:
            async with get_db_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT message_text
                    FROM suggested_messages
                    WHERE is_active = true
                    ORDER BY sort_order
                    """
                )
                return [row["message_text"] for row in rows]
        except Exception as e:
            logger.error(f"Error fetching suggested messages: {e}")
            return []

    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    UPDATE widget_config
                    SET 
                        display_name = $1,
                        initial_message = $2,
                        auto_show_duration = $3,
                        keep_showing_suggested = $4,
                        theme = $5,
                        primary_color = $6,
                        use_primary_for_header = $7,
                        chat_bubble_color = $8,
                        align_bubble = $9,
                        display_chatbot = $10,
                        profile_picture_url = $11,
                        chat_icon_url = $12,
                        profile_picture_filename = $13,
                        chat_icon_filename = $14,
                        profile_zoom = $15,
                        chat_icon_zoom = $16,
                        profile_position = $17,
                        chat_icon_position = $18,
                        updated_at = NOW()
                    WHERE id = 1
                    """,
                    config_data["display_name"],
                    config_data["initial_message"],
                    config_data["auto_show_duration"],
                    config_data["keep_showing_suggested"],
                    config_data["theme"],
                    config_data["primary_color"],
                    config_data["use_primary_for_header"],
                    config_data["chat_bubble_color"],
                    config_data["align_bubble"],
                    config_data["display_chatbot"],
                    config_data.get("profile_picture_url"),
                    config_data.get("chat_icon_url"),
                    config_data.get("profile_picture_filename"),
                    config_data.get("chat_icon_filename"),
                    config_data.get("profile_zoom", 1.0),
                    config_data.get("chat_icon_zoom", 1.0),
                    json.dumps(config_data.get("profile_position", {"x": 0, "y": 0})),
                    json.dumps(config_data.get("chat_icon_position", {"x": 0, "y": 0}))
                )
        except Exception as e:
            logger.error(f"Error updating widget config: {e}")
            raise

    async def update_suggested_messages(self, messages: List[str]):
        """Update suggested messages."""
        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Clear existing messages
                    await conn.execute("DELETE FROM suggested_messages")
                    
                    # Insert new messages
                    for i, message in enumerate(messages):
                        await conn.execute(
                            """
                            INSERT INTO suggested_messages (message_text, sort_order, is_active)
                            VALUES ($1, $2, true)
                            """,
                            message, i
                        )
        except Exception as e:
            logger.error(f"Error updating suggested messages: {e}")
            raise
