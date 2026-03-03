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
        """Get complete chat agent configuration"""
        try:
            # Get all data from appropriate DAOs
            widget_config = await self._widget_dao.get_widget_config()
            security_rows = await self._chat_agent_dao.get_security_settings()
            llm_rows = await self._chat_agent_dao.get_llm_providers()
            persona = await self._chat_agent_dao.get_active_persona()
            human_agents_list = await self._chat_agent_dao.get_human_agents()
            admin_emails_list = await self._chat_agent_dao.get_admins()

            # Build security settings dict
            security = {"response_timeout": 30}
            for row in security_rows:
                if row['setting_name'] == 'response_timeout':
                    security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30

            # Build metadata from widget config (HIL settings stored there)
            metadata = {}
            if widget_config:
                metadata = {
                    "hil_enabled": widget_config.get('hil_enabled', False),
                    "response_policy": widget_config.get('response_policy', 30),
                    "hil_disabled_message": widget_config.get('hil_disabled_message', '')
                }

            # Build LLM tokens dict
            llm_tokens = {}
            for row in llm_rows:
                provider = row['provider_name']
                token_limit = row['token_limit']
                llm_tokens[provider] = token_limit

            return {
                "llm_tokens": llm_tokens,
                "security": security,
                "persona": persona,
                "human_agents": human_agents_list,
                "admin_emails": admin_emails_list,
                "metadata": metadata
            }

        except Exception as e:
            logger.error(f"Error getting chat agent config: {e}")
            raise

    async def save_chatbot_config(self, config: Dict[str, Any]) -> bool:
        """
        Save complete chatbot configuration with batch persistence.
        Updates all configuration components atomically where possible.
        """
        try:
            logger.info(f"💾 Saving chatbot config with fields: {list(config.keys())}")

            if not config:
                logger.warning("⚠️ Empty configuration received")
                return False

            # 1. Update HIL metadata in widget_configuration table
            if 'metadata' in config:
                metadata = config['metadata']
                hil_config = {}
                if 'hil_enabled' in metadata:
                    hil_config['hil_enabled'] = metadata.get('hil_enabled')
                if 'response_policy' in metadata:
                    hil_config['response_policy'] = metadata.get('response_policy')
                if 'hil_disabled_message' in metadata:
                    hil_config['hil_disabled_message'] = metadata.get('hil_disabled_message')

                if hil_config:
                    logger.info(f"📝 Updating HIL metadata: {hil_config}")
                    await self._widget_dao.update_widget_config(hil_config)

            # 2. Sync admin emails (batch operation)
            if 'admin_emails' in config and isinstance(config['admin_emails'], list):
                logger.info(f"👥 Syncing {len(config['admin_emails'])} admin emails")
                await self._chat_agent_dao.sync_admin_emails(config['admin_emails'])

            # 3. Sync human agent emails (batch operation)
            if 'human_agents' in config and isinstance(config['human_agents'], list):
                logger.info(f"🤖 Syncing {len(config['human_agents'])} human agent emails")
                await self._chat_agent_dao.sync_human_agent_emails(config['human_agents'])

            # 4. Update security settings
            if 'security' in config:
                security = config['security']
                if 'response_timeout' in security:
                    logger.info(f"⏱️ Updating response_timeout to {security['response_timeout']}")
                    await self._chat_agent_dao.upsert_security_setting(
                        'response_timeout',
                        str(security['response_timeout']),
                        'integer'
                    )

            # 5. Update persona configuration
            if 'persona' in config:
                persona = config['persona']
                persona_name = persona.get('selected_persona', 'KnowledgeBot')
                system_prompt = persona.get('system_prompt', '')
                logger.info(f"🎭 Updating persona: {persona_name}")
                await self._chat_agent_dao.update_persona(
                    persona_name,
                    system_prompt,
                    is_active=True
                )

            # 6. Update LLM token limits (if provided)
            if 'llm_tokens' in config and isinstance(config['llm_tokens'], dict):
                llm_tokens = config['llm_tokens']
                for provider, tokens_data in llm_tokens.items():
                    if isinstance(tokens_data, dict):
                        limit = tokens_data.get('limit', 20000)
                        used = tokens_data.get('used', 0)
                        logger.info(f"🔑 Updating {provider} tokens: limit={limit}, used={used}")
                        await self._chat_agent_dao.update_llm_provider_tokens(provider, limit, used)

            logger.info(f"✅ Chatbot configuration saved successfully")
            return True

        except Exception as e:
            logger.error(f"Error saving chatbot config: {e}")
            raise

    async def get_widget_config(self) -> Dict[str, Any]:
        """Get widget configuration"""
        try:
            return await self._widget_dao.get_widget_config()
        except Exception as e:
            logger.error(f"Error getting widget config: {e}")
            raise

    async def update_widget_config(self, config: Dict[str, Any]) -> bool:
        """Update widget configuration"""
        try:
            await self._widget_dao.update_widget_config(config)
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

    # Individual configuration data endpoints for progressive loading
    async def get_security_settings(self) -> Dict[str, Any]:
        """Get security settings only"""
        try:
            security_rows = await self._chat_agent_dao.get_security_settings()
            security = {"response_timeout": 30}
            for row in security_rows:
                if row['setting_name'] == 'response_timeout':
                    security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30
            return security
        except Exception as e:
            logger.error(f"Error getting security settings: {e}")
            raise

    async def get_llm_providers(self) -> Dict[str, Any]:
        """Get LLM providers and token usage"""
        try:
            llm_rows = await self._chat_agent_dao.get_llm_providers()
            llm_tokens = {}
            for row in llm_rows:
                provider = row['provider_name']
                token_limit = row['token_limit']
                used_tokens = row['token_used']
                llm_tokens[provider] = {
                    "used": used_tokens,
                    "available": (token_limit - used_tokens),
                    "limit": token_limit
                }
            return llm_tokens
        except Exception as e:
            logger.error(f"Error getting LLM providers: {e}")
            raise

    async def get_active_persona(self) -> Dict[str, Any]:
        """Get active persona configuration"""
        try:
            persona = await self._chat_agent_dao.get_active_persona()
            all_personas = []

            try:
                all_personas = await self._chat_agent_dao.get_all_personas()
                if not persona and all_personas:
                    persona = all_personas[0]
            except Exception as e:
                logger.error(f"Error fetching personas: {e}")

            persona_config = {
                "system_prompt": persona.get('system_prompt', '') if persona else "",
                "selected_persona": persona.get('persona_name', 'KnowledgeBot') if persona else "KnowledgeBot",
                "available_personas": all_personas
            }
            return persona_config
        except Exception as e:
            logger.error(f"Error getting active persona: {e}")
            raise

    async def get_human_agents(self):
        """Get human agents list"""
        try:
            return await self._chat_agent_dao.get_human_agents()
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            raise

    async def get_admin_emails(self):
        """Get admin emails list"""
        try:
            return await self._chat_agent_dao.get_admins()
        except Exception as e:
            logger.error(f"Error getting admin emails: {e}")
            raise

    async def add_human_agent(self, email: str) -> bool:
        """Add a human agent"""
        try:
            return await self._chat_agent_dao.add_human_agent(email)
        except Exception as e:
            logger.error(f"Error adding human agent: {e}")
            raise

    async def remove_human_agent(self, email: str) -> bool:
        """Remove a human agent"""
        try:
            return await self._chat_agent_dao.remove_human_agent(email)
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

    async def remove_admin(self, email: str) -> bool:
        """Remove an admin"""
        try:
            return await self._chat_agent_dao.remove_admin(email)
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            raise
