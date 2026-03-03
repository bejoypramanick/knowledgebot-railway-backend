"""
WidgetConfig Data Access Object for Configuration Service
Handles database operations for widget configuration
"""
from typing import Dict, List, Any, Optional, Tuple
import json

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
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
                profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                hil_enabled, response_policy, hil_disabled_message
            FROM widget_configuration
            WHERE id = 1
        """
        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                row = result.fetchone()
                logger.log_db_query(query, None, row)
                # Convert database row to dictionary
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise  # Raise exception instead of silently returning None

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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, None, rows)
                return [row["message_text"] for row in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def update_widget_config(self, config_data: Dict[str, Any]):
        """
        Update widget configuration with support for partial updates.
        Only updates fields that are provided in config_data.
        """
        try:
            # Build SET clause dynamically - only include provided fields
            set_clauses = []
            params = {}

            # Standard widget config fields
            standard_fields = {
                "display_name": str,
                "initial_message": str,
                "auto_show_duration": int,
                "keep_showing_suggested": bool,
                "theme": str,
                "primary_color": str,
                "use_primary_for_header": bool,
                "chat_bubble_color": str,
                "align_bubble": str,
                "display_chatbot": bool,
                "profile_picture_url": str,
                "chat_icon_url": str,
                "profile_picture_filename": str,
                "chat_icon_filename": str,
                "profile_zoom": float,
                "chat_icon_zoom": float,
                "profile_position": dict,
                "chat_icon_position": dict,
                "hil_enabled": bool,
                "response_policy": int,
                "hil_disabled_message": str
            }

            # Add provided fields to params
            for field_name, field_type in standard_fields.items():
                if field_name in config_data:
                    value = config_data[field_name]
                    if field_name in ("profile_position", "chat_icon_position"):
                        # JSON fields
                        params[field_name] = json.dumps(value)
                        set_clauses.append(f"{field_name} = :{field_name}")
                    else:
                        params[field_name] = value
                        set_clauses.append(f"{field_name} = :{field_name}")

            if not set_clauses:
                logger.info("⚠️ No fields provided to update in widget config")
                return

            # Always update timestamp
            set_clauses.append("updated_at = NOW()")

            query = f"""
                UPDATE widget_configuration
                SET {', '.join(set_clauses)}
                WHERE id = 1
            """

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                logger.info(f"✅ Widget config updated: {len(set_clauses)-1} field(s)")
        except Exception as e:
            logger.log_db_query("update_widget_config", config_data, error=e)
            raise

    async def update_suggested_messages(self, messages: List[str]):
        """Update suggested messages."""
        try:
            async with get_db_session() as session:
                # Get the widget config ID (should be ID 1 for the main config)
                config_id_query = "SELECT id FROM widget_configuration LIMIT 1"
                logger.log_db_operation(config_id_query)
                config_id_result = await session.execute(text(config_id_query))
                config_id_row = config_id_result.fetchone()
                logger.log_db_query(config_id_query, None, config_id_row)

                if not config_id_row:
                    raise ValueError("No widget configuration found")

                widget_config_id = config_id_row["id"]

                # Clear existing messages for this widget config
                delete_query = "DELETE FROM widget_suggested_messages WHERE widget_config_id = :widget_config_id"
                delete_params = {"widget_config_id": widget_config_id}
                logger.log_db_operation(delete_query, delete_params)
                await session.execute(text(delete_query), delete_params)
                logger.log_db_query(delete_query, delete_params, None)

                # Insert new messages
                insert_query = """
                    INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
                    VALUES (:widget_config_id, :message_text, :display_order, true, NOW(), NOW())
                """
                for i, message in enumerate(messages):
                    insert_params = {"widget_config_id": widget_config_id, "message_text": message, "display_order": i}
                    logger.log_db_operation(insert_query, insert_params)
                    await session.execute(text(insert_query), insert_params)
                    logger.log_db_query(insert_query, insert_params, None)

                await session.commit()
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
                SET {url_column} = :storage_url, {filename_column} = :storage_filename, updated_at = NOW()
                WHERE id = 1
            """
            params = {"storage_url": storage_url, "storage_filename": storage_filename}

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return storage_url, storage_filename

        except Exception as e:
            logger.error(f"Error updating widget image '{image_type}': {e}")
            raise

    async def clear_suggested_messages(self):
        """Clear all suggested messages."""
        query = "DELETE FROM widget_suggested_messages"
        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                await session.execute(text(query))
                await session.commit()
                logger.log_db_query(query, None, None)
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def add_suggested_message(self, message: str, index: int):
        """Add a suggested message."""
        query = """
            INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
            VALUES (1, :message_text, :display_order, true, NOW(), NOW())
        """
        params = {"message_text": message, "display_order": index}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def save_widget_config(self, hil_enabled: bool,
                                 hil_disabled_message: str, config_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        DAO method that persists widget configuration.

        This is the master DAO method for widget configuration persistence.
        It handles:
        1. Updating HIL metadata (hil_enabled, hil_disabled_message)
        2. Optionally updating other widget config fields if provided

        Note: response_policy (15-300) is handled by ChatAgentConfigDAO.save_chat_agent_config()
              since it's a chat agent behavior setting, not a widget appearance setting.
        """
        try:
            logger.info(f"💾 [DAO] Persisting widget config")

            # Build base config with HIL fields (response_policy is now in chat agent config)
            hil_config = {
                "hil_enabled": hil_enabled,
                "hil_disabled_message": hil_disabled_message
            }

            # Merge with any additional config data provided
            if config_data:
                hil_config.update(config_data)

            logger.info(f"📝 [DAO] Updating widget config with {len(hil_config)} fields")
            await self.update_widget_config(hil_config)

            logger.info(f"✅ [DAO] Widget config persisted successfully")
            return True

        except Exception as e:
            logger.error(f"❌ [DAO] Error persisting widget config: {e}")
            raise
