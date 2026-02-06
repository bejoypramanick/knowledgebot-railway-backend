"""
ChatAgentConfig Data Access Object for Configuration Service
Handles database operations for admin and agent configuration management
"""
from typing import Dict, List, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("chatbot_dao", "configuration")

class ChatAgentConfigDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get complete widget configuration including metadata."""
        query = """
            SELECT 
                display_name, initial_message, auto_show_duration, keep_showing_suggested,
                theme, primary_color, use_primary_for_header, chat_bubble_color, align_bubble,
                display_chatbot, profile_picture_url, chat_icon_url, profile_picture_filename,
                chat_icon_filename, profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                hil_enabled, response_policy, hil_disabled_message, created_at, updated_at
            FROM widget_configuration
            WHERE id = 1
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    async def update_widget_config(self, **kwargs):
        """Update complete widget configuration including metadata in single call."""
        try:
            async with get_db_connection() as conn:
                # First check if the row exists
                check_query = "SELECT id FROM widget_configuration WHERE id = 1"
                logger.log_db_operation(check_query)
                existing_row = await conn.fetchrow(check_query)
                logger.log_db_query(check_query, None, existing_row)
                
                if not existing_row:
                    # Insert the row if it doesn't exist
                    insert_query = """
                        INSERT INTO widget_configuration (
                            id, display_name, initial_message, auto_show_duration, keep_showing_suggested,
                            theme, primary_color, use_primary_for_header, chat_bubble_color, align_bubble,
                            display_chatbot, profile_picture_url, chat_icon_url, profile_picture_filename,
                            chat_icon_filename, profile_zoom, chat_icon_zoom, profile_position, chat_icon_position,
                            hil_enabled, response_policy, hil_disabled_message, created_at, updated_at
                        ) VALUES (
                            1, $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, NOW(), NOW()
                        )
                    """
                    insert_params = [
                        kwargs.get('display_name', 'GLOBISTAAN'),
                        kwargs.get('initial_message', 'Hi! What can I help you with?'),
                        kwargs.get('auto_show_duration', 30),
                        kwargs.get('keep_showing_suggested', False),
                        kwargs.get('theme', 'light'),
                        kwargs.get('primary_color', '#007bff'),
                        kwargs.get('use_primary_for_header', True),
                        kwargs.get('chat_bubble_color', '#f8f9fa'),
                        kwargs.get('align_bubble', 'right'),
                        kwargs.get('display_chatbot', True),
                        kwargs.get('profile_picture_url'),
                        kwargs.get('chat_icon_url'),
                        kwargs.get('profile_picture_filename'),
                        kwargs.get('chat_icon_filename'),
                        kwargs.get('profile_zoom', 1.00),
                        kwargs.get('chat_icon_zoom', 1.00),
                        kwargs.get('profile_position', {"x": 0, "y": 0}),
                        kwargs.get('chat_icon_position', {"x": 20, "y": 20}),
                        kwargs.get('hil_enabled', True),
                        kwargs.get('response_policy', 30),
                        kwargs.get('hil_disabled_message', 'Human assistance is currently offline. Please leave a message or try again later.')
                    ]
                    logger.log_db_operation(insert_query, insert_params)
                    await conn.execute(insert_query, *insert_params)
                    logger.log_db_query(insert_query, insert_params, "INSERT 1")
                else:
                    # Update existing row with all provided fields
                    set_clauses = []
                    params = []
                    
                    # Define all valid fields that can be updated
                    valid_fields = {
                        'display_name', 'initial_message', 'auto_show_duration', 'keep_showing_suggested',
                        'theme', 'primary_color', 'use_primary_for_header', 'chat_bubble_color', 'align_bubble',
                        'display_chatbot', 'profile_picture_url', 'chat_icon_url', 'profile_picture_filename',
                        'chat_icon_filename', 'profile_zoom', 'chat_icon_zoom', 'profile_position', 'chat_icon_position',
                        'hil_enabled', 'response_policy', 'hil_disabled_message'
                    }
                    
                    for key, value in kwargs.items():
                        if key in valid_fields:
                            set_clauses.append(f"{key} = ${len(params) + 1}")
                            params.append(value)
                    
                    if set_clauses:
                        query = f"""
                            UPDATE widget_configuration
                            SET {', '.join(set_clauses)}, updated_at = NOW()
                            WHERE id = 1
                        """
                        logger.log_db_operation(query, params)
                        result = await conn.execute(query, *params)
                        logger.log_db_query(query, params, result)
                        
        except Exception as e:
            logger.error(f"Error updating widget configuration: {e}")
            raise

    async def get_security_settings(self) -> List[Dict[str, Any]]:
        """Get security settings."""
        query = """
            SELECT setting_name, setting_value, setting_type, description
            FROM security_settings
            ORDER BY setting_name
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def upsert_security_setting(self, name: str, value: str, setting_type: str = 'text'):
        """Upsert security setting."""
        query = """
            INSERT INTO security_settings (setting_name, setting_value, setting_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (setting_name) DO UPDATE SET
            setting_value = EXCLUDED.setting_value, updated_at = NOW()
        """
        params = [name, value, setting_type]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        query = """
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
            AND u.is_active = true 
            AND urm.is_active = true
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                logger.log_db_query(query, None, results)
                return [row['email'] for row in results]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_admins(self) -> List[str]:
        """Get all admin emails."""
        query = """
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
            AND u.is_active = true 
            AND urm.is_active = true
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                logger.log_db_query(query, None, results)
                return [row['email'] for row in results]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_llm_providers(self) -> List[Dict[str, Any]]:
        """Get all LLM providers."""
        query = """
            SELECT id, provider_name, token_limit, token_used, is_active, created_at, updated_at
            FROM llm_providers
            ORDER BY provider_name
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_all_personas(self) -> List[Dict[str, Any]]:
        """Get all personas from database"""
        query = """
            SELECT id, persona_name, system_prompt, 
                    is_active, created_at, updated_at
            FROM public.persona_configurations
            ORDER BY id ASC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise

    async def get_active_persona(self) -> Optional[Dict[str, Any]]:
        """Get active chatbot persona from database."""
        query = """
            SELECT id, persona_name, persona_description, system_prompt, 
                   is_active, created_at, updated_at
            FROM persona_configurations
            WHERE is_active = true
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None
    
    async def update_persona(self, persona_name: str, system_prompt: str, is_active: bool = True):
        """Update existing persona configuration only (no insert)."""
        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    if is_active:
                        deactivate_query = "UPDATE persona_configurations SET is_active = false"
                        logger.log_db_operation(deactivate_query)
                        deactivate_result = await conn.execute(deactivate_query)
                        logger.log_db_query(deactivate_query, None, deactivate_result)
                    
                    update_query = """
                        UPDATE persona_configurations 
                        SET system_prompt = $1, is_active = $2, updated_at = NOW()
                        WHERE persona_name = $3
                    """
                    params = [system_prompt, is_active, persona_name]
                    logger.log_db_operation(update_query, params)
                    result = await conn.execute(update_query, *params)
                    
                    if result == "UPDATE 0":
                        raise ValueError(f"Persona '{persona_name}' not found. Cannot update non-existent persona.")
                    
                    logger.log_db_query(update_query, params, result)
        except Exception as e:
            logger.log_db_query("update_persona", {"persona_name": persona_name, "system_prompt": system_prompt, "is_active": is_active}, error=e)
            raise
