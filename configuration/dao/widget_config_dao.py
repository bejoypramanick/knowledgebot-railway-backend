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
            logger.info("=" * 100)
            logger.info("📖 RETRIEVING SUGGESTED MESSAGES FROM widget_suggested_messages TABLE")
            logger.info("=" * 100)
            logger.info(f"Query: {query}")
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, None, rows)
                messages = [row["message_text"] for row in rows]
                logger.info(f"✅ Retrieved {len(messages)} suggested messages:")
                for i, msg in enumerate(messages, 1):
                    logger.info(f"   [{i}] {msg}")
                logger.info("=" * 100)
                return messages
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            logger.error(f"❌ Error retrieving suggested messages: {e}")
            logger.info("=" * 100)
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
                "response_policy": float,
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
            logger.info(f"📋 [DAO] update_suggested_messages called with {len(messages)} messages: {messages}")
            async with get_db_session() as session:
                # Get the widget config ID (should be ID 1 for the main config)
                config_id_query = "SELECT id FROM widget_configuration LIMIT 1"
                logger.log_db_operation(config_id_query)
                config_id_result = await session.execute(text(config_id_query))
                config_id_row = config_id_result.fetchone()
                logger.log_db_query(config_id_query, None, config_id_row)

                if not config_id_row:
                    logger.error("❌ [DAO] No widget_configuration row found! Cannot insert suggested messages.")
                    raise ValueError("No widget configuration found")

                widget_config_id = config_id_row[0]
                logger.info(f"✅ [DAO] Found widget_config_id: {widget_config_id}")

                # Clear existing messages for this widget config
                delete_query = "DELETE FROM widget_suggested_messages WHERE widget_config_id = :widget_config_id"
                delete_params = {"widget_config_id": widget_config_id}
                logger.log_db_operation(delete_query, delete_params)
                await session.execute(text(delete_query), delete_params)
                logger.info(f"🗑️ [DAO] Deleted existing suggested messages for widget_config_id={widget_config_id}")

                # Insert new messages
                insert_query = """
                    INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
                    VALUES (:widget_config_id, :message_text, :display_order, true, NOW(), NOW())
                """
                logger.info("=" * 100)
                logger.info("📝 INSERTING SUGGESTED MESSAGES INTO widget_suggested_messages TABLE")
                logger.info("=" * 100)
                for i, message in enumerate(messages):
                    insert_params = {"widget_config_id": widget_config_id, "message_text": message, "display_order": i}
                    logger.log_db_operation(insert_query, insert_params)
                    logger.info(f"📤 INSERT QUERY #{i+1}:")
                    logger.info(f"   Query: {insert_query}")
                    logger.info(f"   Params: widget_config_id={widget_config_id}, message_text='{message}', display_order={i}, is_active=true")
                    await session.execute(text(insert_query), insert_params)
                    logger.info(f"✅ [DAO] Inserted message [{i}]: '{message}'")
                logger.info("=" * 100)

                await session.commit()
                logger.info(f"✅ [DAO] Committed {len(messages)} suggested messages successfully")
        except Exception as e:
            logger.error(f"❌ [DAO] Error updating suggested messages: {e}")
            import traceback
            logger.error(f"❌ [DAO] Traceback: {traceback.format_exc()}")
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

    async def get_image_filenames(self) -> dict:
        """Get current image filenames from DB for S3 deletion."""
        query = """
            SELECT profile_picture_filename, chat_icon_filename
            FROM widget_configuration
            WHERE id = 1
        """
        try:
            async with get_db_session() as session:
                result = await session.execute(text(query))
                row = result.fetchone()
                if row:
                    return {
                        "profile_picture_filename": row._mapping.get("profile_picture_filename"),
                        "chat_icon_filename": row._mapping.get("chat_icon_filename")
                    }
                return {"profile_picture_filename": None, "chat_icon_filename": None}
        except Exception as e:
            logger.error(f"Error fetching image filenames: {e}")
            return {"profile_picture_filename": None, "chat_icon_filename": None}

    async def clear_suggested_messages(self):
        """Clear all suggested messages."""
        query = "DELETE FROM widget_suggested_messages"
        try:
            logger.log_db_operation(query)
            logger.info("=" * 100)
            logger.info("🗑️ CLEARING ALL SUGGESTED MESSAGES FROM widget_suggested_messages TABLE")
            logger.info("=" * 100)
            logger.info(f"Query: {query}")
            async with get_db_session() as session:
                result = await session.execute(text(query))
                await session.commit()
                logger.info(f"✅ Deleted {result.rowcount} rows from widget_suggested_messages")
                logger.log_db_query(query, None, None)
                logger.info("=" * 100)
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            logger.error(f"❌ Error clearing suggested messages: {e}")
            logger.info("=" * 100)
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

    async def save_widget_config(self, config_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        DAO method that persists widget configuration.

        This is the master DAO method for widget configuration persistence.
        It handles:
        1. Updating widget appearance fields (display name, colors, themes, etc.)

        Note: HIL settings (hil_enabled, hil_disabled_message, response_policy) are handled by
              ChatAgentConfigDAO.save_chat_agent_config() since they are chat agent behavior settings,
              not widget appearance settings.
        """
        try:
            logger.info(f"💾 [DAO] Persisting widget config")

            # Build config with widget appearance fields only
            widget_config = config_data if config_data else {}

            # If there are config fields to update, call update method
            if widget_config:
                logger.info(f"📝 [DAO] Updating widget config with {len(widget_config)} fields")
                await self.update_widget_config(widget_config)

            logger.info(f"✅ [DAO] Widget config persisted successfully")
            return True

        except Exception as e:
            logger.error(f"❌ [DAO] Error persisting widget config: {e}")
            raise
