"""
ChatAgentConfig Data Access Object for Configuration Service
Handles database operations for admin and agent configuration management
"""
from typing import Dict, List, Any, Optional

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("chatbot_dao", "configuration")

class ChatAgentConfigDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_metadata(self) -> Optional[Dict[str, Any]]:
        """Get chatbot metadata."""
        query = """
            SELECT hil_enabled, response_policy
            FROM configuration_metadata
            WHERE id = 1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    async def update_metadata(self, **kwargs):
        """Update chatbot metadata."""
        try:
            async with get_db_connection() as conn:
                set_clauses = []
                params = []
                
                for key, value in kwargs.items():
                    set_clauses.append(f"{key} = ${len(params) + 1}")
                    params.append(value)
                
                if set_clauses:
                    query = f"""
                        UPDATE configuration_metadata
                        SET {', '.join(set_clauses)}, updated_at = NOW()
                        WHERE id = 1
                    """
                    result = await conn.execute(query, *params)
                    logger.log_db_query(query, params, result)
                    logger.info(f"Updated chatbot metadata: {kwargs}")
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get widget configuration."""
        query = """
            SELECT id, primary_color, chat_icon_url, chat_icon_zoom, 
                   display_chatbot, align_bubble, auto_show_duration,
                   chat_bubble_color, profile_picture_url, profile_zoom,
                   chat_header, chat_welcome_message, suggested_messages
            FROM widget_config
            WHERE id = 1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result
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
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return [record['message_text'] for record in records]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration."""
        try:
            async with get_db_connection() as conn:
                set_clauses = []
                params = []
                
                for key, value in config_data.items():
                    if key in ['primary_color', 'chat_icon_url', 'chat_icon_zoom', 'display_chatbot', 
                               'align_bubble', 'auto_show_duration', 'chat_bubble_color', 
                               'profile_picture_url', 'profile_zoom', 'keep_showing_suggested', 
                               'use_primary_for_header']:
                        set_clauses.append(f"{key} = ${len(params) + 1}")
                        params.append(value)
                
                if set_clauses:
                    query = f"""
                        UPDATE widget_config 
                        SET {', '.join(set_clauses)}, updated_at = NOW()
                        WHERE id = 1
                    """
                    result = await conn.execute(query, *params)
                    logger.log_db_query(query, params, result)
                    logger.info(f"Updated widget config: {config_data}")
        except Exception as e:
            logger.log_db_query("UPDATE widget_config", config_data, error=e)
            raise

    async def get_notification_settings(self) -> List[Dict[str, Any]]:
        """Get notification settings."""
        query = """
            SELECT setting_name, is_enabled, description
            FROM notification_settings
            ORDER BY setting_name
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_security_settings(self) -> List[Dict[str, Any]]:
        """Get security settings."""
        query = """
            SELECT setting_name, setting_value, setting_type, description
            FROM security_settings
            ORDER BY setting_name
        """
        try:
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
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def upsert_notification_setting_with_desc(self, name: str, enabled: bool, description: str):
        query = """
            INSERT INTO notification_settings (setting_name, is_enabled, description)
            VALUES ($1, $2, $3)
            ON CONFLICT (setting_name) DO UPDATE SET
            is_enabled = EXCLUDED.is_enabled, description = EXCLUDED.description, updated_at = NOW()
        """
        params = [name, enabled, description]
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def upsert_security_setting_with_desc(self, name: str, value: str, setting_type: str, description: str):
        query = """
            INSERT INTO security_settings (setting_name, setting_value, setting_type, description)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (setting_name) DO UPDATE SET
            setting_value = EXCLUDED.setting_value, setting_type = EXCLUDED.setting_type, 
            description = EXCLUDED.description, updated_at = NOW()
        """
        params = [name, value, setting_type, description]
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def create_human_agent(self, email: str) -> int:
        """Create a new human agent and return the ID. Returns existing ID if email already exists."""
        try:
            async with get_db_connection() as conn:
                # Try to insert first
                try:
                    insert_query = """
                        INSERT INTO human_agents (email)
                        VALUES ($1)
                        RETURNING id
                    """
                    result = await conn.fetchval(insert_query, email)
                    logger.log_db_query(insert_query, {"email": email}, result)
                    return result
                except asyncpg.exceptions.UniqueViolationError:
                    # If email already exists, return the existing ID
                    select_query = """
                        SELECT id FROM human_agents WHERE email = $1
                    """
                    result = await conn.fetchval(select_query, email)
                    logger.log_db_query(select_query, {"email": email}, result)
                    return result
        except Exception as e:
            logger.log_db_query("CREATE/SELECT human_agents", {"email": email}, error=e)
            raise

    async def delete_human_agent(self, email: str):
        """Delete a human agent by email."""
        query = "DELETE FROM human_agents WHERE email = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.log_db_query(query, {"email": email}, result)
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            raise

    async def get_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        query = "SELECT email FROM human_agents"
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                logger.log_db_query(query, None, results)
                return [row['email'] for row in results]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_admins(self) -> List[str]:
        """Get all admin emails."""
        query = "SELECT email FROM admins WHERE status = 'active'"
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                logger.log_db_query(query, None, results)
                return [row['email'] for row in results]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def sync_admin_emails(self, ui_emails: List[str]) -> Dict[str, List[str]]:
        """Sync admin emails by comparing database with UI request.
        
        Args:
            ui_emails: List of emails from the UI request
            
        Returns:
            Dict with 'added', 'removed', and 'unchanged' email lists
        """
        try:
            async with get_db_connection() as conn:
                # Get current admin emails from database
                current_admins = await self.get_admins()
                current_admins_set = set(current_admins)
                ui_emails_set = set(ui_emails)
                
                # Calculate differences
                to_add = ui_emails_set - current_admins_set  # UI has, DB doesn't
                to_remove = current_admins_set - ui_emails_set  # DB has, UI doesn't
                unchanged = current_admins_set & ui_emails_set  # Both have
                
                # Add new admins
                added_emails = []
                for email in to_add:
                    try:
                        await conn.execute(
                            "INSERT INTO admins (email, status) VALUES ($1, 'active')",
                            email
                        )
                        added_emails.append(email)
                        logger.info(f"Added admin: {email}")
                    except asyncpg.exceptions.UniqueViolationError:
                        # Admin already exists, just update status
                        await conn.execute(
                            "UPDATE admins SET status = 'active' WHERE email = $1",
                            email
                        )
                        added_emails.append(email)
                
                # Remove admins (hard delete from database)
                removed_emails = []
                for email in to_remove:
                    await conn.execute(
                        "DELETE FROM admins WHERE email = $1",
                        email
                    )
                    removed_emails.append(email)
                    logger.info(f"Deleted admin from database: {email}")
                
                return {
                    'added': list(added_emails),
                    'removed': list(removed_emails),
                    'unchanged': list(unchanged)
                }
                
        except Exception as e:
            logger.error(f"Error syncing admin emails: {e}")
            raise

    async def sync_human_agent_emails(self, ui_emails: List[str]) -> Dict[str, List[str]]:
        """Sync human agent emails by comparing database with UI request.
        
        Args:
            ui_emails: List of emails from the UI request
            
        Returns:
            Dict with 'added', 'removed', and 'unchanged' email lists
        """
        try:
            async with get_db_connection() as conn:
                # Get current human agent emails from database
                current_agents = await self.get_human_agents()
                current_agents_set = set(current_agents)
                ui_emails_set = set(ui_emails)
                
                # Calculate differences
                to_add = ui_emails_set - current_agents_set  # UI has, DB doesn't
                to_remove = current_agents_set - ui_emails_set  # DB has, UI doesn't
                unchanged = current_agents_set & ui_emails_set  # Both have
                
                # Add new human agents
                added_emails = []
                for email in to_add:
                    try:
                        await conn.execute(
                            "INSERT INTO human_agents (email) VALUES ($1)",
                            email
                        )
                        added_emails.append(email)
                        logger.info(f"Added human agent: {email}")
                    except asyncpg.exceptions.UniqueViolationError:
                        # Agent already exists, just ensure it's not removed
                        await conn.execute(
                            "UPDATE human_agents SET removed_at = NULL WHERE email = $1",
                            email
                        )
                        added_emails.append(email)
                
                # Remove human agents (hard delete from database)
                removed_emails = []
                for email in to_remove:
                    await conn.execute(
                        "DELETE FROM human_agents WHERE email = $1",
                        email
                    )
                    removed_emails.append(email)
                    logger.info(f"Deleted human agent from database: {email}")
                
                return {
                    'added': list(added_emails),
                    'removed': list(removed_emails),
                    'unchanged': list(unchanged)
                }
                
        except Exception as e:
            logger.error(f"Error syncing human agent emails: {e}")
            raise

    # Session Assignment Methods
    async def get_existing_assignment(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get existing agent assignment for a session."""
        query = """
            SELECT ha.* FROM human_agents ha
            JOIN agent_session_assignments asa ON ha.id = asa.agent_id
            WHERE asa.session_id = $1 AND asa.status = 'active'
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get all available human agents."""
        query = """
            SELECT * FROM human_agents 
            WHERE is_active = true 
            ORDER BY email
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def create_agent_assignment(self, session_id: str, agent_id: int, assigned_by: str):
        """Create a new agent assignment."""
        query = """
            INSERT INTO agent_session_assignments 
            (session_id, agent_id, status, assigned_at, assigned_by)
            VALUES ($1, $2, 'active', NOW(), $3)
            ON CONFLICT (session_id) DO UPDATE SET
            agent_id = EXCLUDED.agent_id, status = EXCLUDED.status, 
            assigned_at = EXCLUDED.assigned_at, assigned_by = EXCLUDED.assigned_by
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_id, agent_id, assigned_by)
                logger.log_db_query(query, {"session_id": session_id, "agent_id": agent_id, "assigned_by": assigned_by}, result)
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "agent_id": agent_id, "assigned_by": assigned_by}, error=e)
            raise

    async def get_llm_providers(self) -> List[Dict[str, Any]]:
        """Get all LLM providers."""
        query = """
            SELECT id, provider_name, token_limit, token_used, is_active, created_at, updated_at
            FROM llm_providers
            ORDER BY provider_name
        """
        
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    # =================================
    # PERSONAS METHODS
    # =================================

    async def get_all_personas(self) -> List[Dict[str, Any]]:
        """Get all personas from database"""
        try:
            async with get_db_connection() as conn:
                query = """
                    SELECT id, persona_name, system_prompt, 
                           is_active, created_at, updated_at
                    FROM public.persona_configurations
                    ORDER BY created_at DESC
                """
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
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None
    
    async def activate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Activate a persona (set is_active to true)"""
        query = """
            UPDATE public.persona_configurations 
            SET is_active = true, updated_at = NOW()
            WHERE persona_name = $1
            RETURNING id, persona_name, system_prompt, 
                     is_active, created_at, updated_at
        """
        try:
            async with get_db_connection() as conn:
                # First check if persona exists
                check_query = """
                    SELECT id, persona_name, system_prompt, 
                           is_active, created_at, updated_at
                    FROM public.persona_configurations
                    WHERE persona_name = $1
                """
                row = await conn.fetchrow(check_query, persona_name)
                logger.log_db_query(check_query, {"persona_name": persona_name}, row)
                
                if not row:
                    raise ValueError(f"Persona '{persona_name}' not found")
                
                # Update the persona to be active
                updated_row = await conn.fetchrow(query, persona_name)
                logger.log_db_query(query, {"persona_name": persona_name}, updated_row)
            
            return dict(updated_row)
        except Exception as e:
            logger.log_db_query(query, {"persona_name": persona_name}, error=e)
            raise

    async def update_persona(self, persona_name: str, system_prompt: str, is_active: bool = True):
        """Update existing persona configuration only (no insert)."""
        try:
            async with get_db_connection() as conn:
                async with conn.transaction():
                    if is_active:
                        deactivate_query = "UPDATE persona_configurations SET is_active = false"
                        deactivate_result = await conn.execute(deactivate_query)
                        logger.log_db_query(deactivate_query, None, deactivate_result)
                    
                    update_query = """
                        UPDATE persona_configurations 
                        SET system_prompt = $1, is_active = $2, updated_at = NOW()
                        WHERE persona_name = $3
                    """
                    params = [system_prompt, is_active, persona_name]
                    result = await conn.execute(update_query, *params)
                    
                    # Check if the persona was actually updated
                    if result == "UPDATE 0":
                        raise ValueError(f"Persona '{persona_name}' not found. Cannot update non-existent persona.")
                    
                    logger.log_db_query(update_query, params, result)
        except Exception as e:
            logger.log_db_query("UPDATE persona_configurations", {"persona_name": persona_name, "system_prompt": system_prompt, "is_active": is_active}, error=e)
            raise
