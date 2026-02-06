"""
WidgetConfig Data Access Object for Configuration Service
Handles database operations for widget configuration
"""
from typing import Dict, List, Any, Optional, Tuple
import json

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger
from configuration.core.railway_storage import railway_storage

logger = get_otel_logger("widget_dao", "configuration")

class WidgetConfigDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get main widget configuration."""
        query = """
            SELECT
                display_name, initial_message, auto_show_duration,
                keep_showing_suggested, theme, primary_color,
                use_primary_for_header, chat_bubble_color, align_bubble,
                display_chatbot, profile_picture_url, chat_icon_url,
                profile_picture_filename, chat_icon_filename,
                profile_zoom, chat_icon_zoom, profile_position, chat_icon_position
            FROM widget_configuration
            WHERE id = 1
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                # Convert database row to dictionary
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    async def get_suggested_messages(self) -> List[str]:
        """Get suggested messages for the widget."""
        query = """
            SELECT message_text
            FROM widget_suggested_messages
            WHERE is_active = true
            ORDER BY display_order
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
                return [row["message_text"] for row in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration."""
        query = """
            UPDATE widget_configuration
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
        """
        params = [
            config_data["display_name"],
            config_data["initial_message"],
            config_data.get("auto_show_duration", 4),  # Default to 4 if None
            config_data.get("keep_showing_suggested", True),  # Default to True if None
            config_data.get("theme", "light"),  # Default to light if None
            config_data.get("primary_color", "#3b82f6"),  # Default if None
            config_data.get("use_primary_for_header", True),  # Default if None
            config_data.get("chat_bubble_color", "#3b82f6"),  # Default if None
            config_data.get("align_bubble", "right"),  # Default if None
            config_data.get("display_chatbot", True),  # Default if None
            config_data.get("profile_picture_url"),
            config_data.get("chat_icon_url"),
            config_data.get("profile_picture_filename"),
            config_data.get("chat_icon_filename"),
            config_data.get("profile_zoom", 1.0),
            config_data.get("chat_icon_zoom", 1.0),
            json.dumps(config_data.get("profile_position", {"x": 0, "y": 0})),
            json.dumps(config_data.get("chat_icon_position", {"x": 0, "y": 0}))
        ]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def update_suggested_messages(self, messages: List[str]):
        """Update suggested messages."""
        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    # Get the widget config ID (should be ID 1 for the main config)
                    config_id_query = "SELECT id FROM widget_configuration LIMIT 1"
                    logger.log_db_operation(config_id_query)
                    config_id_row = await conn.fetchrow(config_id_query)
                    logger.log_db_query(config_id_query, None, config_id_row)
                    
                    if not config_id_row:
                        raise ValueError("No widget configuration found")
                    
                    widget_config_id = config_id_row["id"]
                    
                    # Clear existing messages for this widget config
                    delete_query = "DELETE FROM widget_suggested_messages WHERE widget_config_id = $1"
                    delete_params = {"widget_config_id": widget_config_id}
                    logger.log_db_operation(delete_query, delete_params)
                    delete_result = await conn.execute(delete_query, widget_config_id)
                    logger.log_db_query(delete_query, delete_params, delete_result)
                    
                    # Insert new messages
                    insert_query = """
                        INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
                        VALUES ($1, $2, $3, true, NOW(), NOW())
                    """
                    for i, message in enumerate(messages):
                        insert_params = {"widget_config_id": widget_config_id, "message": message, "display_order": i}
                        logger.log_db_operation(insert_query, insert_params)
                        result = await conn.execute(insert_query, widget_config_id, message, i)
                        logger.log_db_query(insert_query, insert_params, result)
        except Exception as e:
            logger.error(f"Error updating suggested messages: {e}")
            raise

    async def update_widget_image(self, image_type: str, image_data: bytes, filename: str) -> Tuple[str, str]:
        """
        Update widget image by uploading to Railway storage and updating database with URL.
        """
        try:
            # Determine content type from filename or default to JPEG
            content_type = 'image/jpeg'
            if filename.lower().endswith('.png'): content_type = 'image/png'
            elif filename.lower().endswith('.gif'): content_type = 'image/gif'
            elif filename.lower().endswith('.webp'): content_type = 'image/webp'
            elif filename.lower().endswith('.svg'): content_type = 'image/svg+xml'
            
            # Upload to Railway storage with consistent naming
            storage_url, storage_filename = await railway_storage.upload_image(
                image_data, filename, content_type, image_type
            )
            
            column_mapping = {
                "profile": ("profile_picture_url", "profile_picture_filename"),
                "chatIcon": ("chat_icon_url", "chat_icon_filename"),
                "headerIcon": ("profile_picture_url", "profile_picture_filename")
            }
            
            if image_type not in column_mapping:
                logger.error(f"Invalid image type: {image_type}")
                return False, ""
            
            url_column, filename_column = column_mapping[image_type]
            
            query = f"""
                UPDATE widget_configuration
                SET {url_column} = $1, {filename_column} = $2, updated_at = NOW()
                WHERE id = 1
            """
            params = {"storage_url": storage_url, "storage_filename": storage_filename}
            
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, storage_url, storage_filename)
                logger.log_db_query(query, params, result)
                return storage_url, storage_filename
                
        except Exception as e:
            logger.error(f"Error updating widget image '{image_type}': {e}")
            raise

    async def clear_suggested_messages(self):
        """Clear all suggested messages."""
        query = "DELETE FROM widget_suggested_messages"
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.execute(query)
                logger.log_db_query(query, None, result)
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def add_suggested_message(self, message: str, index: int):
        """Add a suggested message."""
        query = """
            INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
            VALUES (1, $1, $2, true, NOW(), NOW())
        """
        params = {"message": message, "index": index}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, message, index)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
