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

    @staticmethod
    def _system_tenant_widget_defaults() -> Dict[str, Any]:
        return {
            "display_name": "System Tenant",
            "initial_message": "Hi! What can I help you with?",
            "auto_show_duration": 30,
            "keep_showing_suggested": False,
            "theme": "light",
            "primary_color": "#007bff",
            "use_primary_for_header": True,
            "chat_bubble_color": "#f8f9fa",
            "align_bubble": "right",
            "display_chatbot": False,
            "profile_picture_url": None,
            "chat_icon_url": None,
            "profile_picture_filename": None,
            "chat_icon_filename": None,
            "profile_zoom": 1.00,
            "chat_icon_zoom": 1.00,
            "profile_position": {"x": 0, "y": 0},
            "chat_icon_position": {"x": 20, "y": 20},
            "hil_enabled": True,
            "response_policy": 30,
            "hil_disabled_message": "Human assistance is currently offline. Please leave a message or try again later.",
            "allowed_origins": [],
        }

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get main widget configuration with self-healing row creation."""
        from shared.tenant_context import get_current_tenant_id, get_current_tenant_slug, DEFAULT_TENANT_ID
        tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID
        tenant_slug = get_current_tenant_slug()

        select_query = """
            SELECT
                display_name, initial_message, auto_show_duration,
                keep_showing_suggested, theme, primary_color,
                use_primary_for_header, chat_bubble_color, align_bubble,
                display_chatbot, profile_picture_url, chat_icon_url,
                profile_picture_filename, chat_icon_filename,
                profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                hil_enabled, response_policy, hil_disabled_message,
                allowed_origins
            FROM widget_configuration
            WHERE is_singleton = true AND tenant_id = CAST(:tenant_id AS UUID)
        """
        params = {"tenant_id": tenant_id}
        try:
            logger.log_db_operation(select_query, params)
            from shared.tenant_context import tenant_context
            with tenant_context(tenant_id=tenant_id):
                async with get_db_session() as session:
                    result = await session.execute(text(select_query), params)
                    row = result.mappings().first()
                    
                    if row:
                        logger.log_db_query(select_query, params, row)
                        return dict(row)

                    if tenant_slug == "system":
                        logger.info(
                            f"ℹ️ No widget configuration found for system tenant {tenant_id}. "
                            "Returning in-memory defaults without self-healing insert."
                        )
                        return self._system_tenant_widget_defaults()
                    
                    # SELF-HEALING: No row found for this tenant, seed a default one
                    logger.warning(f"⚠️ No widget configuration found for tenant {tenant_id}. Seeding default row...")
                    seed_query = """
                        INSERT INTO widget_configuration (tenant_id, is_singleton)
                        VALUES (CAST(:tenant_id AS UUID), true)
                        ON CONFLICT DO NOTHING
                        RETURNING 
                            display_name, initial_message, auto_show_duration,
                            keep_showing_suggested, theme, primary_color,
                            use_primary_for_header, chat_bubble_color, align_bubble,
                            display_chatbot, profile_picture_url, chat_icon_url,
                            profile_picture_filename, chat_icon_filename,
                            profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                            hil_enabled, response_policy, hil_disabled_message,
                            allowed_origins
                    """
                    seed_result = await session.execute(text(seed_query), params)
                    await session.commit()
                    
                    # If ON CONFLICT DO NOTHING happened, fetch again
                    row = seed_result.mappings().first()
                    if not row:
                        result = await session.execute(text(select_query), params)
                        row = result.mappings().first()
                    
                    logger.info(f"✅ Default widget configuration seeded successfully for tenant {tenant_id}")
                    return dict(row) if row else None

        except Exception as e:
            logger.error(f"❌ Error in get_widget_config: {e}")
            raise

    async def get_suggested_messages(self) -> List[str]:
        """Get suggested messages for the widget."""
        from shared.tenant_context import get_current_tenant_id, DEFAULT_TENANT_ID
        tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID

        query = """
            SELECT message_text
            FROM widget_suggested_messages
            WHERE widget_config_id = (
                SELECT id FROM widget_configuration 
                WHERE is_singleton = true AND tenant_id = CAST(:tenant_id AS UUID)
            )
            ORDER BY display_order
        """
        params = {"tenant_id": tenant_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.mappings().all()
                logger.log_db_query(query, params, rows)
                return [row["message_text"] for row in rows]
        except Exception as e:
            error_str = str(e)
            if "does not exist" in error_str or "relation" in error_str:
                return []
            logger.error(f"❌ Error retrieving suggested messages: {e}")
            return []

    async def update_widget_config(self, config_data: Dict[str, Any]):
        """
        Update widget configuration using UPSERT (INSERT ... ON CONFLICT).
        Ensures the row exists and is updated atomically.
        """
        try:
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
                "hil_disabled_message": str,
                "allowed_origins": list,
            }

            columns = ["is_singleton", "updated_at"]
            placeholders = [":is_singleton", "NOW()"]
            update_clauses = ["updated_at = EXCLUDED.updated_at"]
            params = {"is_singleton": True}

            for field_name, _ in standard_fields.items():
                if field_name in config_data:
                    value = config_data[field_name]
                    columns.append(field_name)
                    if field_name in ("profile_position", "chat_icon_position", "allowed_origins"):
                        params[field_name] = json.dumps(value)
                    else:
                        params[field_name] = value
                    placeholders.append(f":{field_name}")
                    update_clauses.append(f"{field_name} = EXCLUDED.{field_name}")

            # USE MULTI-TENANT AWRE ON CONFLICT
            # Note: idx_widget_configuration_tenant_singleton is (tenant_id, is_singleton) WHERE is_singleton = true
            # PostgreSQL requires target columns to match index columns.
            # Explicitly specifying tenant_id in INSERT is better for clarity although default works.
            from shared.tenant_context import get_current_tenant_id, DEFAULT_TENANT_ID
            tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID
            params["tenant_id"] = tenant_id
            columns.append("tenant_id")
            placeholders.append(":tenant_id")

            query = f"""
                INSERT INTO widget_configuration ({', '.join(columns)})
                VALUES ({', '.join(placeholders)})
                ON CONFLICT (tenant_id, is_singleton) WHERE is_singleton = true
                DO UPDATE SET {', '.join(update_clauses)}
            """

            logger.log_db_operation(query, params)
            from shared.tenant_context import tenant_context
            with tenant_context(tenant_id=tenant_id):
                async with get_db_session() as session:
                    await session.execute(text(query), params)
                    await session.commit()
                    logger.info(f"✅ Widget config UPSERT successful: {len(columns)-3} field(s) updated")
        except Exception as e:
            logger.log_db_query("update_widget_config", config_data, error=e)
            logger.error(f"❌ Error in update_widget_config: {e}")
            raise

    async def update_suggested_messages(self, messages: List[str]):
        """Update suggested messages."""
        try:
            logger.info(f"📋 [DAO] update_suggested_messages called with {len(messages)} messages: {messages}")
            async with get_db_session() as session:
                # Get the widget config ID for THIS tenant
                from shared.tenant_context import get_current_tenant_id, DEFAULT_TENANT_ID
                tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID
                config_id_query = "SELECT id FROM widget_configuration WHERE is_singleton = true AND tenant_id = CAST(:tenant_id AS UUID)"
                params = {"tenant_id": tenant_id}
                logger.log_db_operation(config_id_query, params)
                config_id_result = await session.execute(text(config_id_query), params)
                config_id_row = config_id_result.fetchone()
                logger.log_db_query(config_id_query, params, config_id_row)

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
                for i, message in enumerate(messages):
                    insert_params = {"widget_config_id": widget_config_id, "message_text": message, "display_order": i}
                    await session.execute(text(insert_query), insert_params)
                    logger.info(f"✅ [DAO] Inserted message [{i}]")

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

            from shared.tenant_context import get_current_tenant_id, DEFAULT_TENANT_ID
            tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID

            query = f"""
                UPDATE widget_configuration
                SET {url_column} = :storage_url, {filename_column} = :storage_filename, updated_at = NOW()
                WHERE is_singleton = true AND tenant_id = CAST(:tenant_id AS UUID)
            """
            params = {
                "storage_url": storage_url, 
                "storage_filename": storage_filename,
                "tenant_id": tenant_id
            }

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
        from shared.tenant_context import get_current_tenant_id, DEFAULT_TENANT_ID
        tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID

        query = """
            SELECT profile_picture_filename, chat_icon_filename
            FROM widget_configuration
            WHERE is_singleton = true AND tenant_id = CAST(:tenant_id AS UUID)
        """
        params = {"tenant_id": tenant_id}
        try:
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
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
        from shared.tenant_context import get_current_tenant_id, DEFAULT_TENANT_ID
        tenant_id = get_current_tenant_id() or DEFAULT_TENANT_ID

        query = """
            INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
            VALUES ((SELECT id FROM widget_configuration WHERE is_singleton = true AND tenant_id = CAST(:tenant_id AS UUID)), :message_text, :display_order, true, NOW(), NOW())
        """
        params = {"message_text": message, "display_order": index, "tenant_id": tenant_id}
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
