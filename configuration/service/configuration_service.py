"""
Configuration Service for Chat Agent and Widget Configuration
Provides business logic layer for configuration operations
"""
from typing import Any, Dict, Optional

from configuration.core.otel_logger import get_otel_logger
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
            # Get all data via unified widget configuration call
            widget_config = await self._chat_agent_dao.get_widget_config()
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

            # Build metadata from widget config (HIL settings)
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
        """Save complete chatbot configuration"""
        try:
            await self._chat_agent_dao.save_chatbot_config(config)
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
