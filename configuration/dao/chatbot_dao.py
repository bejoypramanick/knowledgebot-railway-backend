from typing import Any, Dict, List, Optional
import asyncpg

from configuration.core.logging_config import get_railway_logger
from configuration.core.db import get_db_connection
from configuration.core.db_logger import execute_with_logging, fetchrow_with_logging, fetch_with_logging

logger = get_railway_logger(__name__)

class ChatbotDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_metadata(self) -> Optional[Dict[str, Any]]:
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                """
                SELECT default_user_role, hil_enabled, response_policy
                FROM configuration_metadata
                WHERE id = 1
                """
            )

    async def get_notification_settings(self) -> List[Dict[str, Any]]:
        async with get_db_connection() as conn:
            return await conn.fetch(
                """
                SELECT setting_name, is_enabled
                FROM notification_settings
                ORDER BY setting_name
                """
            )

    async def get_security_settings(self) -> List[Dict[str, Any]]:
        async with get_db_connection() as conn:
            return await conn.fetch(
                """
                SELECT setting_name, setting_value, setting_type
                FROM security_settings
                ORDER BY setting_name
                """
            )

    async def get_active_persona(self) -> Optional[Dict[str, Any]]:
        """Get active chatbot persona from database."""
        try:
            async with get_db_connection() as conn:
                # Check if table exists first
                table_exists = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        AND table_name = 'persona_configurations'
                    )
                    """
                )
                
                if not table_exists:
                    logger.warning("persona_configurations table does not exist, returning fallback persona")
                    return {
                        'persona_name': 'KnowledgeBot',
                        'persona_description': 'A helpful AI assistant for knowledge management',
                        'is_active': True,
                        'system_prompt': 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.'
                    }
                
                # Try to get active persona from database
                query = """
                    SELECT persona_name, system_prompt, is_active
                    FROM persona_configurations
                    WHERE is_active = true
                    LIMIT 1
                """
                
                persona = await fetchrow_with_logging(conn, query, operation="GET_ACTIVE_PERSONA")
                
                if persona:
                    return {
                        'persona_name': persona['persona_name'],
                        'persona_description': f"AI assistant: {persona['persona_name']}",
                        'is_active': persona['is_active'],
                        'system_prompt': persona['system_prompt']
                    }
                else:
                    # Fallback to default persona if no active persona found
                    return {
                        'persona_name': 'KnowledgeBot',
                        'persona_description': 'A helpful AI assistant for knowledge management',
                        'is_active': True,
                        'system_prompt': 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.'
                    }
        except Exception as e:
            logger.error(f"Error getting active persona: {e}")
            # Return fallback persona in case of database error
            return {
                'persona_name': 'KnowledgeBot',
                'persona_description': 'A helpful AI assistant for knowledge management',
                'is_active': True,
                'system_prompt': 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.'
            }

    async def get_llm_providers(self) -> List[Dict[str, Any]]:
        """Get LLM providers for this service."""
        async with get_db_connection() as conn:
            return await conn.fetch(
                """
                SELECT provider_name, token_used, token_limit
                FROM llm_providers
                WHERE is_active = true
                ORDER BY provider_name
                """
            )

    async def add_llm_provider(self, provider: str, limit: int):
        """Add LLM provider for this service."""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO llm_providers (provider_name, token_limit, is_active)
                VALUES ($1, $2, true)
                ON CONFLICT (provider_name) DO UPDATE SET
                token_limit = EXCLUDED.token_limit, updated_at = NOW()
                """,
                provider, limit
            )

    async def update_llm_used_tokens(self, provider: str, used: int):
        """Update LLM token usage for this service."""
        async with get_db_connection() as conn:
            await conn.execute("UPDATE llm_providers SET token_used = $1 WHERE provider_name = $2", used, provider)

    async def update_metadata(self, **kwargs):
        """Update chatbot metadata with dynamic parameters"""
        if not kwargs:
            return
        
        # Use the existing upsert method which handles dynamic updates
        await self.upsert_configuration_metadata(kwargs)

    async def upsert_notification_setting(self, name: str, enabled: bool):
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO notification_settings (setting_name, is_enabled)
                VALUES ($1, $2)
                ON CONFLICT (setting_name) DO UPDATE SET
                is_enabled = EXCLUDED.is_enabled, updated_at = NOW()
                """,
                name, enabled
            )

    async def upsert_security_setting(self, name: str, value: str, setting_type: str = 'text'):
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO security_settings (setting_name, setting_value, setting_type)
                VALUES ($1, $2, $3)
                ON CONFLICT (setting_name) DO UPDATE SET
                setting_value = EXCLUDED.setting_value, updated_at = NOW()
                """,
                name, value, setting_type
            )

    async def upsert_persona(self, persona_name: str, system_prompt: str, is_active: bool = True):
        async with get_db_connection() as conn:
            async with conn.transaction():
                if is_active:
                    deactivate_query = "UPDATE persona_configurations SET is_active = false"
                    await execute_with_logging(conn, deactivate_query, operation="DEACTIVATE_ALL_PERSONAS")
                
                upsert_query = """
                    INSERT INTO persona_configurations (persona_name, system_prompt, is_active)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (persona_name) DO UPDATE SET
                    system_prompt = EXCLUDED.system_prompt, is_active = EXCLUDED.is_active, updated_at = NOW()
                """
                params = [persona_name, system_prompt, is_active]
                result = await execute_with_logging(conn, upsert_query, *params, operation="UPSERT_PERSONA")

    async def upsert_configuration_metadata(self, updates_dict: Dict[str, Any]):
        """Upsert configuration metadata using proper PostgreSQL syntax"""
        if not updates_dict:
            return
        
        # Build column lists and values
        columns = list(updates_dict.keys())
        values = list(updates_dict.values())
        
        # Build the INSERT query with proper type casting
        column_definitions = []
        value_placeholders = []
        update_clauses = []
        
        for i, (column, value) in enumerate(updates_dict.items()):
            # Determine PostgreSQL type
            if column == 'hil_enabled':
                pg_type = 'boolean'
            elif column == 'response_policy':
                pg_type = 'integer'
            else:
                pg_type = 'text'
            
            column_definitions.append(column)
            value_placeholders.append(f'${i+2}::{pg_type}')
            update_clauses.append(f"{column} = EXCLUDED.{column}")
        
        query = f"""
        INSERT INTO configuration_metadata (id, {', '.join(column_definitions)})
        VALUES ($1, {', '.join(value_placeholders)})
        ON CONFLICT (id) DO UPDATE SET {', '.join(update_clauses)}, updated_at = CURRENT_TIMESTAMP
        """
        
        # Execute with id=1 as the first parameter
        all_values = [1] + values
        
        async with get_db_connection() as conn:
            result = await execute_with_logging(conn, query, *all_values, operation="UPSERT_CONFIGURATION_METADATA")
    
    def _get_postgres_type(self, column_name: str) -> str:
        """Get PostgreSQL type for configuration metadata columns"""
        type_mapping = {
            'hil_enabled': 'boolean',
            'response_policy': 'integer',
            'default_user_role': 'text'
        }
        return type_mapping.get(column_name, 'text')

    async def upsert_notification_setting_with_desc(self, name: str, enabled: bool, description: str):
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO notification_settings (setting_name, is_enabled, description)
                VALUES ($1, $2, $3)
                ON CONFLICT (setting_name) DO UPDATE SET
                is_enabled = EXCLUDED.is_enabled, description = EXCLUDED.description, updated_at = NOW()
                """,
                name, enabled, description
            )

    async def upsert_security_setting_with_desc(self, name: str, value: str, setting_type: str, description: str):
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO security_settings (setting_name, setting_value, setting_type, description)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (setting_name) DO UPDATE SET
                setting_value = EXCLUDED.setting_value, setting_type = EXCLUDED.setting_type, 
                description = EXCLUDED.description, updated_at = NOW()
                """,
                name, value, setting_type, description
            )

    # Human Agent Management Methods
    async def create_human_agent(self, email: str) -> int:
        """Create a new human agent and return the ID. Returns existing ID if email already exists."""
        async with get_db_connection() as conn:
            # Try to insert first
            try:
                return await conn.fetchval(
                    """
                    INSERT INTO human_agents (email)
                    VALUES ($1)
                    RETURNING id
                    """,
                    email
                )
            except asyncpg.exceptions.UniqueViolationError:
                # If email already exists, return the existing ID
                return await conn.fetchval(
                    """
                    SELECT id FROM human_agents WHERE email = $1
                    """,
                    email
                )

    async def delete_human_agent(self, email: str):
        """Delete a human agent by email."""
        async with get_db_connection() as conn:
            await conn.execute(
                "DELETE FROM human_agents WHERE email = $1",
                email
            )

    async def get_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    "SELECT email FROM human_agents"
                )
                return [row['email'] for row in results]
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            return []

    async def get_admins(self) -> List[str]:
        """Get all admin emails."""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    "SELECT email FROM admins WHERE status = 'active'"
                )
                return [row['email'] for row in results]
        except Exception as e:
            logger.error(f"Error getting admins: {e}")
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
                        await execute_with_logging(
                            conn, 
                            "INSERT INTO admins (email, status) VALUES ($1, 'active')", 
                            email, 
                            operation="INSERT_ADMIN"
                        )
                        added_emails.append(email)
                        logger.info(f"Added admin: {email}")
                    except asyncpg.exceptions.UniqueViolationError:
                        # Admin already exists, just update status
                        await execute_with_logging(
                            conn, 
                            "UPDATE admins SET status = 'active' WHERE email = $1", 
                            email, 
                            operation="UPDATE_ADMIN_STATUS"
                        )
                        added_emails.append(email)
                
                # Remove admins (hard delete from database)
                removed_emails = []
                for email in to_remove:
                    await execute_with_logging(
                        conn, 
                        "DELETE FROM admins WHERE email = $1", 
                        email, 
                        operation="DELETE_ADMIN"
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
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                """
                SELECT ha.* FROM human_agents ha
                JOIN agent_session_assignments asa ON ha.id = asa.agent_id
                WHERE asa.session_id = $1 AND asa.status = 'active'
                """,
                session_id
            )

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get all available human agents."""
        async with get_db_connection() as conn:
            return await conn.fetch(
                """
                SELECT * FROM human_agents 
                WHERE is_active = true 
                ORDER BY email
                """
            )

    async def create_agent_assignment(self, session_id: str, agent_id: int, assigned_by: str):
        """Create a new agent assignment."""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO agent_session_assignments 
                (session_id, agent_id, status, assigned_at, assigned_by)
                VALUES ($1, $2, 'active', NOW(), $3)
                ON CONFLICT (session_id) DO UPDATE SET
                agent_id = EXCLUDED.agent_id, status = EXCLUDED.status, 
                assigned_at = EXCLUDED.assigned_at, assigned_by = EXCLUDED.assigned_by
                """,
                session_id, agent_id, assigned_by
            )
