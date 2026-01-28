import logging
from typing import Optional, Dict, Any, List, Union
from ..schemas.models import ChatbotConfigRequest

logger = logging.getLogger(__name__)

class ChatbotDAO:
    def __init__(self, connection):
        self.conn = connection

    async def get_metadata(self) -> Optional[Dict[str, Any]]:
        return await self.conn.fetchrow(
            """
            SELECT default_user_role, hil_enabled, response_policy
            FROM configuration_metadata
            WHERE id = 1
            """
        )

    async def get_notification_settings(self) -> List[Dict[str, Any]]:
        return await self.conn.fetch(
            """
            SELECT setting_name, is_enabled
            FROM notification_settings
            ORDER BY setting_name
            """
        )

    async def get_security_settings(self) -> List[Dict[str, Any]]:
        return await self.conn.fetch(
            """
            SELECT setting_name, setting_value, setting_type
            FROM security_settings
            ORDER BY setting_name
            """
        )

    async def get_llm_providers(self) -> List[Dict[str, Any]]:
        return await self.conn.fetch(
            """
            SELECT provider_name, token_limit, token_used
            FROM llm_providers
            WHERE is_active = true
            ORDER BY provider_name
            """
        )

    async def get_active_persona(self) -> Optional[Dict[str, Any]]:
        return await self.conn.fetchrow(
            """
            SELECT persona_name, system_prompt
            FROM persona_configurations
            WHERE is_active = true
            LIMIT 1
            """
        )

    async def get_human_agents(self) -> List[str]:
        rows = await self.conn.fetch(
            """
            SELECT email FROM human_agents
            ORDER BY email
            """
        )
        return [r["email"] for r in rows] if rows else []

    async def get_admins(self) -> List[str]:
        rows = await self.conn.fetch(
            """
            SELECT email FROM admins
            ORDER BY email
            """
        )
        return [r["email"] for r in rows] if rows else []

    async def update_metadata(self, hil_enabled: bool, response_policy: int):
        await self.conn.execute(
            """
            UPDATE configuration_metadata
            SET hil_enabled = $1, response_policy = $2, updated_at = NOW()
            WHERE id = 1
            """,
            hil_enabled, response_policy
        )

    async def upsert_notification_setting(self, name: str, enabled: bool):
        await self.conn.execute(
            """
            INSERT INTO notification_settings (setting_name, is_enabled)
            VALUES ($1, $2)
            ON CONFLICT (setting_name) DO UPDATE SET is_enabled = EXCLUDED.is_enabled
            """,
            name, enabled
        )

    async def upsert_security_setting(self, name: str, value: str, setting_type: str = 'text'):
        await self.conn.execute(
            """
            INSERT INTO security_settings (setting_name, setting_value, setting_type)
            VALUES ($1, $2, $3)
            ON CONFLICT (setting_name) DO UPDATE SET 
                setting_value = EXCLUDED.setting_value,
                setting_type = EXCLUDED.setting_type
            """,
            name, value, setting_type
        )

    async def upsert_persona(self, persona_name: str, system_prompt: str, is_active: bool = True):
        async with self.conn.transaction():
            if is_active:
                await self.conn.execute("UPDATE persona_configurations SET is_active = false")
            
            await self.conn.execute(
                """
                INSERT INTO persona_configurations (persona_name, system_prompt, is_active)
                VALUES ($1, $2, $3)
                ON CONFLICT (persona_name) DO UPDATE SET
                    system_prompt = EXCLUDED.system_prompt,
                    is_active = EXCLUDED.is_active
                """,
                persona_name, system_prompt, is_active
            )

    async def update_llm_tokens(self, provider: str, limit: int):
        await self.conn.execute(
            """
            INSERT INTO llm_providers (provider_name, token_limit, is_active)
            VALUES ($1, $2, true)
            ON CONFLICT (provider_name) DO UPDATE SET token_limit = EXCLUDED.token_limit
            """,
            provider, limit
        )

    async def update_llm_used_tokens(self, provider: str, used: int):
        await self.conn.execute("UPDATE llm_providers SET token_used = $1 WHERE provider_name = $2", used, provider)

    async def add_admin(self, email: str):
        await self.conn.execute(
            """
            INSERT INTO admins (email)
            VALUES ($1)
            ON CONFLICT (email) DO NOTHING
            """,
            email
        )

    async def remove_admin(self, email: str):
        await self.conn.execute("DELETE FROM admins WHERE email = $1", email)

    async def find_human_agent(self, email: str) -> Optional[Dict[str, Any]]:
        return await self.conn.fetchrow("SELECT id FROM human_agents WHERE email = $1", email)

    async def add_human_agent(self, email: str):
        await self.conn.execute(
            """
            INSERT INTO human_agents (email)
            VALUES ($1)
            ON CONFLICT (email) DO NOTHING
            """,
            email
        )

    async def remove_human_agent(self, email: str):
        await self.conn.execute("DELETE FROM human_agents WHERE email = $1", email)

    async def clear_human_agents(self):
         await self.conn.execute("DELETE FROM human_agents")

    async def upsert_configuration_metadata(self, updates_dict: Dict[str, Any]):
        if not updates_dict:
            return
            
        columns = list(updates_dict.keys())
        values = list(updates_dict.values())
        
        placeholders = [f"${i+2}" for i in range(len(columns))]
        set_clause = [f"{col} = ${i+2}" for i, col in enumerate(columns)]
        
        query = f"""
        INSERT INTO configuration_metadata (id, {', '.join(columns)})
        VALUES (1, {', '.join(placeholders)})
        ON CONFLICT (id) DO UPDATE SET {', '.join(set_clause)}, updated_at = CURRENT_TIMESTAMP
        """
        await self.conn.execute(query, 1, *values)

    async def upsert_notification_setting_with_desc(self, name: str, enabled: bool, description: str):
        await self.conn.execute(
            """
            INSERT INTO notification_settings (setting_name, is_enabled, description)
            VALUES ($1, $2, $3)
            ON CONFLICT (setting_name) DO UPDATE SET is_enabled = EXCLUDED.is_enabled
            """,
            name, enabled, description
        )

    async def upsert_security_setting_with_desc(self, name: str, value: str, setting_type: str, description: str):
        await self.conn.execute(
            """
            INSERT INTO security_settings (setting_name, setting_value, setting_type, description)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (setting_name) DO UPDATE SET setting_value = EXCLUDED.setting_value
            """,
            name, value, setting_type, description
        )

    # Human Agent Management Methods
    async def create_human_agent(self, email: str) -> int:
        """Create a new human agent and return the ID."""
        return await self.conn.fetchval(
            """
            INSERT INTO human_agents (email)
            VALUES ($1)
            RETURNING id
            """,
            email
        )

    async def get_all_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents."""
        return await self.conn.fetch("SELECT email FROM human_agents")

    async def delete_human_agent(self, email: str):
        """Delete a human agent by email."""
        await self.conn.execute(
            "DELETE FROM human_agents WHERE email = $1",
            email
        )

    # Session Assignment Methods
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session details by session ID."""
        return await self.conn.fetchrow(
            "SELECT * FROM chat_sessions WHERE session_id = $1",
            session_id
        )

    async def get_existing_assignment(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get existing agent assignment for a session."""
        return await self.conn.fetchrow(
            """
            SELECT ha.* FROM human_agents ha
            JOIN agent_session_assignments asa ON ha.id = asa.agent_id
            WHERE asa.session_id = $1 AND asa.status = 'active'
            """,
            session_id
        )

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get all available human agents."""
        return await self.conn.fetch(
            """
            SELECT * FROM human_agents 
            WHERE is_active = true 
            ORDER BY created_at ASC
            """
        )

    async def create_agent_assignment(self, session_id: str, agent_id: int, assigned_by: str):
        """Create a new agent assignment."""
        await self.conn.execute(
            """
            INSERT INTO agent_session_assignments 
            (session_id, agent_id, status, assigned_at, assigned_by)
            VALUES ($1, $2, 'active', CURRENT_TIMESTAMP, $3)
            """,
            session_id, agent_id, assigned_by
        )
