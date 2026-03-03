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
