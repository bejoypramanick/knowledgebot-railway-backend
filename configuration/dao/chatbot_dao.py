from typing import Any, Dict, List, Optional

from shared.db import get_db_connection
from shared.logging_config import get_railway_logger

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
        """Get active chatbot persona (fallback to default since chatbot_personas table doesn't exist)."""
        try:
            # Return default persona since chatbot_personas table doesn't exist
            return {
                'persona_name': 'KnowledgeBot',
                'persona_description': 'A helpful AI assistant for knowledge management',
                'is_active': True,
                'system_prompt': 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.'
            }
        except Exception as e:
            logger.error(f"Error getting active persona: {e}")
            return None

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

    async def update_metadata(self, hil_enabled: bool, response_policy: int):
        async with get_db_connection() as conn:
            await conn.execute(
                """
                UPDATE configuration_metadata
                SET hil_enabled = $1, response_policy = $2, updated_at = NOW()
                WHERE id = 1
                """,
                hil_enabled, response_policy
            )

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
                    await conn.execute("UPDATE persona_configurations SET is_active = false")
                
                await conn.execute(
                    """
                    INSERT INTO persona_configurations (persona_name, system_prompt, is_active)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (persona_name) DO UPDATE SET
                    system_prompt = EXCLUDED.system_prompt, is_active = EXCLUDED.is_active, updated_at = NOW()
                    """,
                    persona_name, system_prompt, is_active
                )

    async def upsert_configuration_metadata(self, updates_dict: Dict[str, Any]):
        if not updates_dict:
            return
        
        placeholders = []
        values = []
        set_clause = []
        
        for i, (key, value) in enumerate(updates_dict.items(), 2):
            placeholders.append(f"${i}")
            values.append(value)
            set_clause.append(f"{key} = EXCLUDED.{key}")
        
        query = f"""
        INSERT INTO configuration_metadata (id, {', '.join(updates_dict.keys())})
        VALUES (1, {', '.join(placeholders)})
        ON CONFLICT (id) DO UPDATE SET {', '.join(set_clause)}, updated_at = CURRENT_TIMESTAMP
        """
        async with get_db_connection() as conn:
            await conn.execute(query, 1, *values)

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
        """Create a new human agent and return the ID."""
        async with get_db_connection() as conn:
            return await conn.fetchval(
                """
                INSERT INTO human_agents (email)
                VALUES ($1)
                RETURNING id
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
                    "SELECT email FROM human_agents WHERE removed_at IS NULL"
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
