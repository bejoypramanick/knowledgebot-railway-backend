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
            logger.info(f"🔍 DAO update_metadata called with kwargs: {kwargs}")
            async with get_db_connection() as conn:
                set_clauses = []
                params = []
                
                for key, value in kwargs.items():
                    set_clauses.append(f"{key} = ${len(params) + 1}")
                    params.append(value)
                    logger.info(f"🔍 Adding clause: {key} = ${len(params)} with value: {value}")
                
                if set_clauses:
                    query = f"""
                        UPDATE configuration_metadata
                        SET {', '.join(set_clauses)}, updated_at = NOW()
                        WHERE id = 1
                    """
                    logger.info(f"🔍 Executing query: {query}")
                    logger.info(f"🔍 With params: {params}")
                    result = await conn.execute(query, *params)
                    logger.log_db_query(query, params, result)
                    logger.info(f"✅ Updated chatbot metadata: {kwargs}")
                else:
                    logger.warning("⚠️ No set clauses generated for metadata update")
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            logger.error(f"❌ Error in update_metadata: {e}")
            raise


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
