"""
ChatAgentConfig Data Access Object for Configuration Service
Handles database operations for admin and agent configuration management
"""
from typing import Dict, List, Any, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("chatbot_dao", "configuration")

class ChatAgentConfigDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get complete widget configuration including metadata."""
        query = text("""
            SELECT
                display_name, initial_message, auto_show_duration, keep_showing_suggested,
                theme, primary_color, use_primary_for_header, chat_bubble_color, align_bubble,
                display_chatbot, profile_picture_url, chat_icon_url, profile_picture_filename,
                chat_icon_filename, profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                hil_enabled, response_policy, hil_disabled_message, created_at, updated_at
            FROM widget_configuration
            WHERE id = 1
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                result = await session.execute(query)
                row = result.fetchone()
                logger.log_db_query(str(query), None, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            raise  # ← Raise exception instead of silently returning None

    async def update_widget_config(self, **kwargs):
        """Update complete widget configuration including metadata in single call."""
        try:
            async with get_db_session() as session:
                # First check if the row exists
                check_query = text("SELECT id FROM widget_configuration WHERE id = 1")
                logger.log_db_operation(str(check_query))
                existing_row = await session.execute(check_query)
                existing_result = existing_row.fetchone()
                logger.log_db_query(str(check_query), None, existing_result)

                if not existing_result:
                    # Insert the row if it doesn't exist
                    insert_query = text("""
                        INSERT INTO widget_configuration (
                            id, display_name, initial_message, auto_show_duration, keep_showing_suggested,
                            theme, primary_color, use_primary_for_header, chat_bubble_color, align_bubble,
                            display_chatbot, profile_picture_url, chat_icon_url, profile_picture_filename,
                            chat_icon_filename, profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                            hil_enabled, response_policy, hil_disabled_message, created_at, updated_at
                        ) VALUES (
                            1, :display_name, :initial_message, :auto_show_duration, :keep_showing_suggested,
                            :theme, :primary_color, :use_primary_for_header, :chat_bubble_color, :align_bubble,
                            :display_chatbot, :profile_picture_url, :chat_icon_url, :profile_picture_filename,
                            :chat_icon_filename, :profile_zoom, :chat_icon_zoom, :profile_position, :chat_icon_position,
                            :hil_enabled, :response_policy, :hil_disabled_message, NOW(), NOW()
                        )
                    """)
                    insert_params = {
                        'display_name': kwargs.get('display_name', 'GLOBISTAAN'),
                        'initial_message': kwargs.get('initial_message', 'Hi! What can I help you with?'),
                        'auto_show_duration': kwargs.get('auto_show_duration', 30),
                        'keep_showing_suggested': kwargs.get('keep_showing_suggested', False),
                        'theme': kwargs.get('theme', 'light'),
                        'primary_color': kwargs.get('primary_color', '#007bff'),
                        'use_primary_for_header': kwargs.get('use_primary_for_header', True),
                        'chat_bubble_color': kwargs.get('chat_bubble_color', '#f8f9fa'),
                        'align_bubble': kwargs.get('align_bubble', 'right'),
                        'display_chatbot': kwargs.get('display_chatbot', True),
                        'profile_picture_url': kwargs.get('profile_picture_url'),
                        'chat_icon_url': kwargs.get('chat_icon_url'),
                        'profile_picture_filename': kwargs.get('profile_picture_filename'),
                        'chat_icon_filename': kwargs.get('chat_icon_filename'),
                        'profile_zoom': kwargs.get('profile_zoom', 1.00),
                        'chat_icon_zoom': kwargs.get('chat_icon_zoom', 1.00),
                        'profile_position': kwargs.get('profile_position', {"x": 0, "y": 0}),
                        'chat_icon_position': kwargs.get('chat_icon_position', {"x": 20, "y": 20}),
                        'hil_enabled': kwargs.get('hil_enabled', True),
                        'response_policy': kwargs.get('response_policy', 30),
                        'hil_disabled_message': kwargs.get('hil_disabled_message', 'Human assistance is currently offline. Please leave a message or try again later.')
                    }
                    logger.log_db_operation(str(insert_query), insert_params)
                    await session.execute(insert_query, insert_params)
                    logger.log_db_query(str(insert_query), insert_params, "INSERT 1")
                    await session.commit()
                else:
                    # Update existing row with provided fields
                    valid_fields = {
                        'display_name', 'initial_message', 'auto_show_duration', 'keep_showing_suggested',
                        'theme', 'primary_color', 'use_primary_for_header', 'chat_bubble_color', 'align_bubble',
                        'display_chatbot', 'profile_picture_url', 'chat_icon_url', 'profile_picture_filename',
                        'chat_icon_filename', 'profile_zoom', 'chat_icon_zoom', 'profile_position', 'chat_icon_position',
                        'hil_enabled', 'response_policy', 'hil_disabled_message'
                    }

                    # Filter to only valid fields
                    update_data = {k: v for k, v in kwargs.items() if k in valid_fields}

                    if update_data:
                        # Add updated_at timestamp
                        update_data['updated_at'] = text('NOW()')

                        # Build simple UPDATE query
                        query = text("""
                            UPDATE widget_configuration
                            SET display_name = :display_name,
                                initial_message = :initial_message,
                                auto_show_duration = :auto_show_duration,
                                keep_showing_suggested = :keep_showing_suggested,
                                theme = :theme,
                                primary_color = :primary_color,
                                use_primary_for_header = :use_primary_for_header,
                                chat_bubble_color = :chat_bubble_color,
                                align_bubble = :align_bubble,
                                display_chatbot = :display_chatbot,
                                profile_picture_url = :profile_picture_url,
                                chat_icon_url = :chat_icon_url,
                                profile_picture_filename = :profile_picture_filename,
                                chat_icon_filename = :chat_icon_filename,
                                profile_zoom = :profile_zoom,
                                chat_icon_zoom = :chat_icon_zoom,
                                profile_position = :profile_position,
                                chat_icon_position = :chat_icon_position,
                                hil_enabled = :hil_enabled,
                                response_policy = :response_policy,
                                hil_disabled_message = :hil_disabled_message,
                                updated_at = NOW()
                            WHERE id = 1
                        """)

                        logger.log_db_operation(str(query), update_data)
                        await session.execute(query, update_data)
                        logger.log_db_query(str(query), update_data, "UPDATE 1")
                        await session.commit()

        except Exception as e:
            logger.error(f"Error updating widget configuration: {e}")
            raise

    async def get_security_settings(self) -> List[Dict[str, Any]]:
        """Get security settings."""
        query = text("""
            SELECT setting_name, setting_value, setting_type, description
            FROM security_settings
            ORDER BY setting_name
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                result = await session.execute(query)
                rows = result.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            raise  # ← Raise exception instead of silently returning []

    async def upsert_security_setting(self, name: str, value: str, setting_type: str = 'text'):
        """Upsert security setting."""
        query = text("""
            INSERT INTO security_settings (setting_name, setting_value, setting_type)
            VALUES (:name, :value, :setting_type)
            ON CONFLICT (setting_name) DO UPDATE SET
            setting_value = EXCLUDED.setting_value, updated_at = NOW()
        """)
        params = {'name': name, 'value': value, 'setting_type': setting_type}
        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                await session.execute(query, params)
                logger.log_db_query(str(query), params, "UPSERT 1")
                await session.commit()
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            raise

    async def get_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        query = text("""
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
            AND u.is_active = true
            AND urm.is_active = true
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [row.email for row in rows] if rows else []
        except Exception as e:
            logger.error(f"Error fetching human agents: {type(e).__name__}")
            raise  # ← Raise exception instead of silently returning []

    async def get_admins(self) -> List[str]:
        """Get all admin emails."""
        query = text("""
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
            AND u.is_active = true
            AND urm.is_active = true
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [row.email for row in rows] if rows else []
        except Exception as e:
            logger.error(f"Error fetching admin emails: {type(e).__name__}")
            raise  # ← Raise exception instead of silently returning []

    async def get_llm_providers(self) -> List[Dict[str, Any]]:
        """Get all LLM providers."""
        query = text("""
            SELECT id, provider_name, token_limit, token_used, is_active, created_at, updated_at
            FROM llm_providers
            ORDER BY provider_name
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                result = await session.execute(query)
                rows = result.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            raise  # ← Raise exception instead of silently returning []

    async def get_all_personas(self) -> List[Dict[str, Any]]:
        """Get all personas from database"""
        query = text("""
            SELECT id, persona_name, system_prompt,
                    is_active, created_at, updated_at
            FROM public.persona_configurations
            ORDER BY id ASC
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                rows = await session.execute(query)
                result = rows.fetchall()
                logger.log_db_query(str(query), None, result)
                return [dict(row._mapping) for row in result]  # ← Return inside try block
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise  # Already raises, this is fine

    async def get_active_persona(self) -> Optional[Dict[str, Any]]:
        """Get active chatbot persona from database."""
        query = text("""
            SELECT id, persona_name, persona_description, system_prompt,
                   is_active, created_at, updated_at
            FROM persona_configurations
            WHERE is_active = true
            ORDER BY created_at DESC
            LIMIT 1
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                result = await session.execute(query)
                row = result.fetchone()
                logger.log_db_query(str(query), None, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            raise  # ← Raise exception instead of silently returning None
    
    async def update_persona(self, persona_name: str, system_prompt: str, is_active: bool = True):
        """Update existing persona configuration only (no insert)."""
        try:
            async with get_db_session() as session:
                if is_active:
                    deactivate_query = text("UPDATE persona_configurations SET is_active = false")
                    logger.log_db_operation(str(deactivate_query))
                    await session.execute(deactivate_query)
                    logger.log_db_query(str(deactivate_query), None, "UPDATE")

                update_query = text("""
                    UPDATE persona_configurations
                    SET system_prompt = :system_prompt, is_active = :is_active, updated_at = NOW()
                    WHERE persona_name = :persona_name
                """)
                params = {
                    'system_prompt': system_prompt,
                    'is_active': is_active,
                    'persona_name': persona_name
                }
                logger.log_db_operation(str(update_query), params)
                result = await session.execute(update_query, params)

                if result.rowcount == 0:
                    raise ValueError(f"Persona '{persona_name}' not found. Cannot update non-existent persona.")

                logger.log_db_query(str(update_query), params, f"UPDATE {result.rowcount}")
                await session.commit()
        except Exception as e:
            logger.log_db_query("update_persona", {"persona_name": persona_name, "system_prompt": system_prompt, "is_active": is_active}, error=e)
            raise
