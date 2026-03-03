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

    async def add_human_agent(self, email: str) -> bool:
        """Add a human agent by email. Creates user if doesn't exist."""
        try:
            # First ensure user exists
            check_query = text("SELECT id FROM users WHERE email = :email")
            async with get_db_session() as session:
                result = await session.execute(check_query, {"email": email})
                user_row = result.fetchone()
                user_id = user_row.id if user_row else None

                # Create user if doesn't exist
                if not user_id:
                    create_query = text("""
                        INSERT INTO users (email, created_at, updated_at)
                        VALUES (:email, NOW(), NOW())
                        RETURNING id
                    """)
                    logger.log_db_operation(str(create_query), {"email": email})
                    result = await session.execute(create_query, {"email": email})
                    user_row = result.fetchone()
                    user_id = user_row.id if user_row else None
                    logger.log_db_query(str(create_query), {"email": email}, user_row)

                # Get role_id for human_agent
                role_query = text("SELECT id FROM roles WHERE role_name = 'human_agent'")
                logger.log_db_operation(str(role_query))
                result = await session.execute(role_query)
                role_row = result.fetchone()

                if not role_row:
                    raise ValueError("human_agent role not found in database")

                role_id = role_row.id
                logger.log_db_query(str(role_query), None, role_row)

                # Add user role mapping
                mapping_query = text("""
                    INSERT INTO user_role_mapping (user_id, role_id, created_at, updated_at)
                    VALUES (:user_id, :role_id, NOW(), NOW())
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    RETURNING user_role_id
                """)
                params = {"user_id": user_id, "role_id": role_id}
                logger.log_db_operation(str(mapping_query), params)
                result = await session.execute(mapping_query, params)
                mapping_row = result.fetchone()
                logger.log_db_query(str(mapping_query), params, mapping_row)

                await session.commit()
                return mapping_row is not None
        except Exception as e:
            logger.log_db_query("add_human_agent", {"email": email}, error=e)
            raise

    async def remove_human_agent(self, email: str) -> bool:
        """Remove human_agent role from a user."""
        try:
            query = text("""
                DELETE FROM user_role_mapping
                WHERE user_id = (SELECT id FROM users WHERE email = :email)
                AND role_id = (SELECT id FROM roles WHERE role_name = 'human_agent')
            """)
            params = {"email": email}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                logger.log_db_query(str(query), params, f"DELETE {result.rowcount}")
                await session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.log_db_query("remove_human_agent", {"email": email}, error=e)
            raise

    async def add_admin(self, email: str) -> bool:
        """Add an admin by email. Creates user if doesn't exist."""
        try:
            # First ensure user exists
            check_query = text("SELECT id FROM users WHERE email = :email")
            async with get_db_session() as session:
                result = await session.execute(check_query, {"email": email})
                user_row = result.fetchone()
                user_id = user_row.id if user_row else None

                # Create user if doesn't exist
                if not user_id:
                    create_query = text("""
                        INSERT INTO users (email, created_at, updated_at)
                        VALUES (:email, NOW(), NOW())
                        RETURNING id
                    """)
                    logger.log_db_operation(str(create_query), {"email": email})
                    result = await session.execute(create_query, {"email": email})
                    user_row = result.fetchone()
                    user_id = user_row.id if user_row else None
                    logger.log_db_query(str(create_query), {"email": email}, user_row)

                # Get role_id for admin
                role_query = text("SELECT id FROM roles WHERE role_name = 'admin'")
                logger.log_db_operation(str(role_query))
                result = await session.execute(role_query)
                role_row = result.fetchone()

                if not role_row:
                    raise ValueError("admin role not found in database")

                role_id = role_row.id
                logger.log_db_query(str(role_query), None, role_row)

                # Add user role mapping
                mapping_query = text("""
                    INSERT INTO user_role_mapping (user_id, role_id, created_at, updated_at)
                    VALUES (:user_id, :role_id, NOW(), NOW())
                    ON CONFLICT (user_id, role_id) DO NOTHING
                    RETURNING user_role_id
                """)
                params = {"user_id": user_id, "role_id": role_id}
                logger.log_db_operation(str(mapping_query), params)
                result = await session.execute(mapping_query, params)
                mapping_row = result.fetchone()
                logger.log_db_query(str(mapping_query), params, mapping_row)

                await session.commit()
                return mapping_row is not None
        except Exception as e:
            logger.log_db_query("add_admin", {"email": email}, error=e)
            raise

    async def remove_admin(self, email: str) -> bool:
        """Remove admin role from a user."""
        try:
            query = text("""
                DELETE FROM user_role_mapping
                WHERE user_id = (SELECT id FROM users WHERE email = :email)
                AND role_id = (SELECT id FROM roles WHERE role_name = 'admin')
            """)
            params = {"email": email}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                logger.log_db_query(str(query), params, f"DELETE {result.rowcount}")
                await session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.log_db_query("remove_admin", {"email": email}, error=e)
            raise

    async def sync_admin_emails(self, desired_emails: List[str]) -> None:
        """
        Sync admin emails: add missing, remove extra.
        Compares desired state with current state and makes only necessary changes.
        """
        try:
            # Get current admins from database
            current_admins = await self.get_admins()

            # Calculate diffs
            desired_set = set(desired_emails)
            current_set = set(current_admins)
            to_add = desired_set - current_set
            to_remove = current_set - desired_set

            logger.info(f"📊 Admin sync: current={len(current_set)}, desired={len(desired_set)}, to_add={len(to_add)}, to_remove={len(to_remove)}")

            # Apply changes
            for email in to_add:
                logger.info(f"➕ Adding admin: {email}")
                await self.add_admin(email)

            for email in to_remove:
                logger.info(f"➖ Removing admin: {email}")
                await self.remove_admin(email)

            logger.info(f"✅ Admin sync completed: added {len(to_add)}, removed {len(to_remove)}")
        except Exception as e:
            logger.error(f"Error syncing admin emails: {e}")
            raise

    async def sync_human_agent_emails(self, desired_emails: List[str]) -> None:
        """
        Sync human agent emails: add missing, remove extra.
        Compares desired state with current state and makes only necessary changes.
        """
        try:
            # Get current human agents from database
            current_agents = await self.get_human_agents()

            # Calculate diffs
            desired_set = set(desired_emails)
            current_set = set(current_agents)
            to_add = desired_set - current_set
            to_remove = current_set - desired_set

            logger.info(f"📊 Human agent sync: current={len(current_set)}, desired={len(desired_set)}, to_add={len(to_add)}, to_remove={len(to_remove)}")

            # Apply changes
            for email in to_add:
                logger.info(f"➕ Adding human agent: {email}")
                await self.add_human_agent(email)

            for email in to_remove:
                logger.info(f"➖ Removing human agent: {email}")
                await self.remove_human_agent(email)

            logger.info(f"✅ Human agent sync completed: added {len(to_add)}, removed {len(to_remove)}")
        except Exception as e:
            logger.error(f"Error syncing human agent emails: {e}")
            raise

    async def update_llm_provider_tokens(self, provider: str, limit: int, used: int) -> bool:
        """Update token limits and usage for an LLM provider"""
        try:
            query = text("""
                UPDATE llm_providers
                SET token_limit = :limit, token_used = :used, updated_at = NOW()
                WHERE provider_name = :provider
            """)
            params = {"provider": provider, "limit": limit, "used": used}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                logger.log_db_query(str(query), params, f"UPDATE {result.rowcount}")
                await session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.log_db_query("update_llm_provider_tokens", {"provider": provider, "limit": limit, "used": used}, error=e)
            raise

    async def save_chat_agent_config(self, admin_emails: List[str], human_agents: List[str],
                                     response_timeout: int, response_policy: int,
                                     hil_enabled: bool, hil_disabled_message: str,
                                     persona_name: str, system_prompt: str,
                                     llm_tokens: Dict[str, Dict[str, int]]) -> bool:
        """
        DAO method that persists complete chat agent configuration.
        Orchestrates all chat agent related updates in one operation.

        This is the master DAO method for chat agent configuration persistence.
        It handles:
        1. Syncing admin emails
        2. Syncing human agent emails
        3. Updating response timeout (security setting)
        4. Updating response policy (HIL policy - 15-300 seconds)
        5. Updating HIL enabled/disabled status
        6. Updating HIL disabled message
        7. Updating active persona
        8. Updating LLM provider tokens
        """
        try:
            logger.info(f"💾 [DAO] Persisting chat agent config")

            # 1. Sync admin emails
            logger.info(f"👥 [DAO] Syncing {len(admin_emails)} admin emails")
            await self.sync_admin_emails(admin_emails)

            # 2. Sync human agent emails
            logger.info(f"🤖 [DAO] Syncing {len(human_agents)} human agent emails")
            await self.sync_human_agent_emails(human_agents)

            # 3. Update response timeout (security setting)
            logger.info(f"⏱️ [DAO] Updating response_timeout to {response_timeout}")
            await self.upsert_security_setting(
                'response_timeout',
                str(response_timeout),
                'integer'
            )

            # 4. Update response policy (HIL policy - 15-300 seconds)
            logger.info(f"📋 [DAO] Updating response_policy to {response_policy}")
            await self.upsert_security_setting(
                'response_policy',
                str(response_policy),
                'integer'
            )

            # 5. Update HIL enabled status
            logger.info(f"🎛️ [DAO] Updating hil_enabled to {hil_enabled}")
            await self.upsert_security_setting(
                'hil_enabled',
                str(hil_enabled),
                'boolean'
            )

            # 6. Update HIL disabled message
            logger.info(f"💬 [DAO] Updating hil_disabled_message")
            await self.upsert_security_setting(
                'hil_disabled_message',
                hil_disabled_message,
                'text'
            )

            # 7. Update active persona
            logger.info(f"🎭 [DAO] Updating persona: {persona_name}")
            await self.update_persona(persona_name, system_prompt, is_active=True)

            # 8. Update LLM provider tokens
            logger.info(f"🔑 [DAO] Updating {len(llm_tokens)} LLM providers")
            for provider, tokens_data in llm_tokens.items():
                limit = tokens_data.get('limit', 20000)
                used = tokens_data.get('used', 0)
                await self.update_llm_provider_tokens(provider, limit, used)

            logger.info(f"✅ [DAO] Chat agent config persisted successfully")
            return True

        except Exception as e:
            logger.error(f"❌ [DAO] Error persisting chat agent config: {e}")
            raise
