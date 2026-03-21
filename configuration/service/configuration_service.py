"""
Configuration Service for Chat Agent and Widget Configuration
Provides business logic layer for configuration operations
"""
from typing import Any, Dict, Optional

from shared.otel_logger import get_otel_logger
from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
from configuration.dao.widget_config_dao import WidgetConfigDAO

logger = get_otel_logger("configuration_service", "configuration")


class ConfigurationService:
    """Service layer for configuration operations"""

    def __init__(self):
        self._chat_agent_dao = ChatAgentConfigDAO()
        self._widget_dao = WidgetConfigDAO()

    async def get_chatAgent_config(self) -> Dict[str, Any]:
        """Get complete chat agent configuration.

        Delegates to ChatAgentConfigService which runs all 7 DAO reads
        in parallel via asyncio.gather().
        """
        from configuration.service.chat_agent_config_service import ChatAgentConfigService
        svc = ChatAgentConfigService()
        return await svc.get_chatAgent_config()

    async def save_chatbot_config(self, config: Dict[str, Any]) -> bool:
        """
        Save complete chatbot configuration with batch persistence.
        Delegates to DAO methods for all persistence operations.

        Service layer responsibility: validate and extract config, then call DAOs.
        DAO layer responsibility: execute all DML operations.
        """
        try:
            logger.info(f"💾 [SERVICE] Saving chatbot config with fields: {list(config.keys())}")

            if not config:
                logger.warning("⚠️ Empty configuration received")
                return False

            # Extract widget config (appearance only - HIL moved to chat agent config)
            additional_widget_config = {}

            # Extract chat agent config - use ID-based sync
            admin_entries = config.get('admin_emails', [])
            agent_entries = config.get('human_agents', [])

            # Split entries into existing IDs and new emails
            admin_existing_ids = [item["id"] for item in admin_entries if isinstance(item, dict) and "id" in item]
            admin_new_emails = [item["email"] for item in admin_entries if isinstance(item, dict) and "id" not in item and "email" in item]
            # Backward compat: plain strings are treated as new emails
            admin_new_emails += [item for item in admin_entries if isinstance(item, str)]

            agent_existing_ids = [item["id"] for item in agent_entries if isinstance(item, dict) and "id" in item]
            agent_new_emails = [item["email"] for item in agent_entries if isinstance(item, dict) and "id" not in item and "email" in item]
            agent_new_emails += [item for item in agent_entries if isinstance(item, str)]

            response_timeout = 30
            response_policy = 0.5  # Response policy (0=Strict, 1=Flexi, default=Balanced)
            hil_enabled = False
            hil_disabled_message = ""
            persona_name = 'KnowledgeBot'
            system_prompt = ''
            llm_tokens = {}

            if 'security' in config:
                response_timeout = config['security'].get('response_timeout', 30)

            if 'metadata' in config:
                metadata = config['metadata']
                response_policy = metadata.get('response_policy', 0.5)  # Response policy (0-1 range)
                hil_enabled = metadata.get('hil_enabled', False)  # HIL enabled (chat agent setting)
                hil_disabled_message = metadata.get('hil_disabled_message', '')  # HIL message (chat agent setting)

            if 'persona' in config:
                persona = config['persona']
                persona_name = persona.get('selected_persona', 'KnowledgeBot')
                system_prompt = persona.get('system_prompt', '')

            if 'llm_tokens' in config:
                llm_tokens = config['llm_tokens']

            # Delegate to DAO methods (all persistence happens in DAOs)
            logger.info(f"[SERVICE] Delegating to DAO layer for persistence")

            # Persist widget config via DAO (appearance settings only)
            if additional_widget_config:
                await self._widget_dao.save_widget_config(
                    config_data=additional_widget_config if additional_widget_config else None
                )

            # Persist chat agent config via DAO (includes HIL settings and response_policy)
            # Sync admins and agents using ID-based methods
            logger.info(f"👥 Syncing admins: keep_ids={admin_existing_ids}, new_emails={admin_new_emails}")
            await self._chat_agent_dao.sync_admins(admin_existing_ids, admin_new_emails)

            logger.info(f"🤖 Syncing human agents: keep_ids={agent_existing_ids}, new_emails={agent_new_emails}")
            await self._chat_agent_dao.sync_human_agents(agent_existing_ids, agent_new_emails)

            # Persist other settings via DAO
            await self._chat_agent_dao.upsert_security_setting('response_timeout', str(response_timeout), 'integer')
            await self._chat_agent_dao.upsert_security_setting('response_policy', str(response_policy), 'integer')
            await self._chat_agent_dao.upsert_security_setting('hil_enabled', str(hil_enabled), 'boolean')
            await self._chat_agent_dao.upsert_security_setting('hil_disabled_message', hil_disabled_message, 'string')
            await self._chat_agent_dao.update_persona(persona_name, system_prompt, is_active=True)

            for provider, tokens_data in llm_tokens.items():
                limit_val = tokens_data.get('limit', 20000)
                used_val = tokens_data.get('used', 0)
                await self._chat_agent_dao.update_llm_provider_tokens(provider, limit_val, used_val)

            logger.info(f"✅ [SERVICE] Chatbot configuration persisted successfully (via DAOs)")
            return True

        except Exception as e:
            logger.error(f"Error saving chatbot config: {e}")
            raise

    async def get_widget_config(self) -> Dict[str, Any]:
        """Get widget configuration with suggested messages"""
        try:
            # Use WidgetConfigService which includes suggested messages
            from configuration.service.widget_config_service import widget_config_service
            return await widget_config_service.get_widget_config()
        except Exception as e:
            logger.error(f"Error getting widget config: {e}")
            raise

    async def update_widget_config(self, config: Dict[str, Any]) -> bool:
        """Update widget configuration"""
        try:
            # Extract suggested messages before passing to main config update
            suggested_messages = config.pop('suggested_messages', None)

            await self._widget_dao.update_widget_config(config)

            # Update suggested messages if provided
            if suggested_messages is not None:
                logger.info(f"💾 Updating {len(suggested_messages)} suggested messages in database...")
                await self._widget_dao.update_suggested_messages(suggested_messages)
                logger.info(f"✅ Suggested messages updated successfully")

            return True
        except Exception as e:
            logger.error(f"Error updating widget config: {e}")
            raise

    async def update_widget_image(self, image_type: str, data_url: str, filename: str) -> bool:
        """Update widget image"""
        try:
            await self._widget_dao.update_widget_image(image_type, data_url, filename)
            return True
        except Exception as e:
            logger.error(f"Error updating widget image: {e}")
            raise

    async def get_human_agents(self):
        """Get human agents list with {id, email} for display"""
        try:
            agents = await self._chat_agent_dao.get_human_agents()
            return [{"id": a["id"], "email": a["email"]} for a in agents]
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            raise

    async def add_human_agent(self, email: str) -> bool:
        """Add a human agent"""
        try:
            return await self._chat_agent_dao.add_human_agent(email)
        except Exception as e:
            logger.error(f"Error adding human agent: {e}")
            raise

    async def remove_human_agent(self, user_id: str) -> bool:
        """Remove a human agent by user ID"""
        try:
            return await self._chat_agent_dao.remove_human_agent_by_id(user_id)
        except Exception as e:
            logger.error(f"Error removing human agent: {e}")
            raise

    async def add_admin(self, email: str) -> bool:
        """Add an admin"""
        try:
            return await self._chat_agent_dao.add_admin(email)
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            raise

    async def remove_admin(self, user_id: str) -> bool:
        """Remove an admin by user ID"""
        try:
            return await self._chat_agent_dao.remove_admin_by_id(user_id)
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            raise
