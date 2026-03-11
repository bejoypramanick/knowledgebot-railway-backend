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
        import time
        start_time = time.time()
        logger.info("[ENTRY] ConfigurationService.get_chatAgent_config()")
        
        try:
            # Get all data from appropriate DAOs
            logger.info("[FLOW] Fetching widget_config from DAO")
            widget_config = await self._widget_dao.get_widget_config()
            logger.info(f"[RESULT] widget_config retrieved: {bool(widget_config)}")
            
            logger.info("[FLOW] Fetching security_settings from DAO")
            security_rows = await self._chat_agent_dao.get_security_settings()
            logger.info(f"[RESULT] security_rows count: {len(security_rows)}")
            
            logger.info("[FLOW] Fetching llm_providers from DAO")
            llm_rows = await self._chat_agent_dao.get_llm_providers()
            logger.info(f"[RESULT] llm_rows count: {len(llm_rows)}")
            
            logger.info("[FLOW] Fetching active_persona from DAO")
            persona = await self._chat_agent_dao.get_active_persona()
            logger.info(f"[RESULT] persona retrieved: {bool(persona)}")
            
            logger.info("[FLOW] Fetching human_agents from DAO")
            human_agents_list = await self._chat_agent_dao.get_human_agents()
            logger.info(f"[RESULT] human_agents count: {len(human_agents_list)}")
            
            logger.info("[FLOW] Fetching admin_emails from DAO")
            admin_emails_list = await self._chat_agent_dao.get_admins()
            logger.info(f"[RESULT] admin_emails count: {len(admin_emails_list)}")

            # Build security settings dict
            logger.info("[TRANSFORM] Building security settings dict")
            security = {"response_timeout": 30}
            for row in security_rows:
                if row['setting_name'] == 'response_timeout':
                    security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30
            logger.info(f"[RESULT] security dict: {security}")

            # Build metadata from widget config (HIL settings stored there)
            logger.info("[TRANSFORM] Building metadata from widget_config")
            metadata = {}
            if widget_config:
                metadata = {
                    "hil_enabled": widget_config.get('hil_enabled', False),
                    "response_policy": widget_config.get('response_policy', 0.5),
                    "hil_disabled_message": widget_config.get('hil_disabled_message', '')
                }
            logger.info(f"[RESULT] metadata dict: {metadata}")

            # Build LLM tokens dict
            logger.info("[TRANSFORM] Building llm_tokens dict")
            llm_tokens = {}
            for row in llm_rows:
                provider = row['provider_name']
                token_limit = row['token_limit']
                llm_tokens[provider] = token_limit
            logger.info(f"[RESULT] llm_tokens dict keys: {list(llm_tokens.keys())}")

            result = {
                "llm_tokens": llm_tokens,
                "security": security,
                "persona": persona,
                "human_agents": human_agents_list,
                "admin_emails": admin_emails_list,
                "metadata": metadata
            }
            
            elapsed_time = time.time() - start_time
            logger.info(f"[EXIT] ConfigurationService.get_chatAgent_config() - Success (elapsed: {elapsed_time:.3f}s)")
            logger.info(f"[RETURN] Result keys: {list(result.keys())}")
            return result

        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"[EXIT] ConfigurationService.get_chatAgent_config() - Error (elapsed: {elapsed_time:.3f}s)")
            logger.error(f"[ERROR] Exception type: {type(e).__name__}, Message: {str(e)}")
            raise

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

            # Extract chat agent config
            admin_emails = config.get('admin_emails', [])
            human_agents = config.get('human_agents', [])
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
            if admin_emails or human_agents or response_timeout or response_policy or hil_enabled or hil_disabled_message or persona_name or llm_tokens:
                await self._chat_agent_dao.save_chat_agent_config(
                    admin_emails=admin_emails,
                    human_agents=human_agents,
                    response_timeout=response_timeout,
                    response_policy=response_policy,
                    hil_enabled=hil_enabled,
                    hil_disabled_message=hil_disabled_message,
                    persona_name=persona_name,
                    system_prompt=system_prompt,
                    llm_tokens=llm_tokens
                )

            logger.info(f"✅ [SERVICE] Chatbot configuration persisted successfully (via DAOs)")
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
            security = {
                "response_timeout": 30,
                "response_policy": 0.5,
                "hil_enabled": False,
                "hil_disabled_message": ""
            }
            for row in security_rows:
                setting_name = row['setting_name']
                setting_value = row['setting_value']
                setting_type = row['setting_type']

                if setting_name == 'response_timeout' and setting_type == 'integer':
                    security['response_timeout'] = int(setting_value)
                elif setting_name == 'response_policy' and setting_type in ('integer', 'float'):
                    security['response_policy'] = float(setting_value)
                elif setting_name == 'hil_enabled' and setting_type == 'boolean':
                    security['hil_enabled'] = setting_value.lower() in ('true', '1', 't', 'yes')
                elif setting_name == 'hil_disabled_message' and setting_type == 'string':
                    security['hil_disabled_message'] = setting_value
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
