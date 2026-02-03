"""
Chat Agent Configuration Service for Chat Agent Management
Provides business logic layer for chat agent configuration operations
"""
from typing import Any, Dict, List, Optional

from configuration.core.otel_logger import get_otel_logger
from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO

logger = get_otel_logger("chat_agent_config_service", "configuration")

class ChatAgentConfigService:
    """Service layer for chat agent configuration operations"""

    def __init__(self):
        self._chatAgent_dao = ChatAgentConfigDAO()
    
    async def get_chatAgent_config(self):
        """Get complete chatbot configuration with all data transformations"""
        try:
            # Get all raw data via direct DAO calls
            metadata = await self._chatAgent_dao.get_metadata()
            security_rows = await self._chatAgent_dao.get_security_settings()
            llm_rows = await self._chatAgent_dao.get_llm_providers()
            persona = await self._chatAgent_dao.get_active_persona()
            human_agents_list = await self._chatAgent_dao.get_human_agents()
            admin_emails_list = await self._chatAgent_dao.get_admins()

            # Build security settings dict
            security = {
                "response_timeout": 30
            }
            for row in security_rows:
                if row['setting_name'] == 'response_timeout':
                    security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30
               
            # Build LLM tokens dict using llm_providers table data
            llm_tokens = {}
            for row in llm_rows:
                provider = row['provider_name']
                token_limit = row['token_limit'] or 0
                token_used = row['token_used'] or 0
                available_tokens = max(0, token_limit - token_used)
                
                llm_tokens[provider] = {
                    "used": token_used,
                    "available": available_tokens,
                    "limit": token_limit
                }
            
            # Ensure gemini provider exists with defaults if not in database
            if 'gemini' not in llm_tokens:
                llm_tokens['gemini'] = {
                    "used": 0,
                    "available": 0,
                    "limit": 0
                }
            
            logger.info(f"✅ LLM tokens constructed from llm_providers table: {llm_tokens}")

            # Initialize persona config with active persona
            persona_config = {
                "system_prompt": persona.get('system_prompt', '') if persona else "",
                "selected_persona": persona.get('persona_name', 'KnowledgeBot') if persona else "KnowledgeBot"
            }

            # Get all available personas
            try:
                all_personas = await self._chatAgent_dao.get_all_personas()
                
                # Use first persona as default if no active persona is set
                if not persona and all_personas:
                    first_persona = all_personas[0]
                    persona_config = {
                        "system_prompt": first_persona.get('system_prompt', ''),
                        "selected_persona": first_persona.get('persona_name', 'KnowledgeBot')
                    }
                    
            except Exception as e:
                logger.error(f"Error fetching personas: {e}")
                all_personas = []

            # Build response
            response = {
                "admin_emails": admin_emails_list,
                "human_agents": human_agents_list,
                "security": security,
                "llm_tokens": llm_tokens,
                "persona": persona_config,
                "available_personas": all_personas,
                "metadata": metadata
            }

            logger.info("✅ Chatbot config retrieved successfully")
            return response

        except Exception as e:
            logger.error(f"Error getting chatbot configuration: {e}")
            raise

    async def save_chatAgent_config(self, config_data: Dict[str, Any]):
        """Save complete chatbot configuration"""
        try:
            logger.info(f"🔍 Saving chatbot config: {config_data}")
            
            # Save metadata if provided
            if 'metadata' in config_data:
                metadata = config_data['metadata']
                if isinstance(metadata, dict):
                    await self._chatAgent_dao.update_metadata(**metadata)
            
            # Save security settings
            if 'security' in config_data:
                security = config_data['security']
                if isinstance(security, dict):
                    if 'response_timeout' in security:
                        await self._chatAgent_dao.upsert_security_setting(
                            'response_timeout', 
                            str(security['response_timeout']), 
                            'integer'
                        )
                    if 'remove_pii' in security:
                        await self._chatAgent_dao.upsert_security_setting(
                            'remove_pii', 
                            str(security['remove_pii']).lower(), 
                            'boolean'
                        )
                    if 'restrict_config' in security:
                        await self._chatAgent_dao.upsert_security_setting(
                            'restrict_config', 
                            str(security['restrict_config']).lower(), 
                            'boolean'
                        )
            
            # Save admin emails if provided
            if 'admin_emails' in config_data:
                admin_emails = config_data['admin_emails']
                if isinstance(admin_emails, list):
                    await self._chatAgent_dao.sync_admin_emails(admin_emails)
            
            # Save human agents if provided
            if 'human_agents' in config_data:
                human_agents = config_data['human_agents']
                if isinstance(human_agents, list):
                    await self._chatAgent_dao.sync_human_agent_emails(human_agents)
            
            # Update LLM tokens if provided
            if 'llm_tokens' in config_data:
                llm_tokens = config_data['llm_tokens']
                if isinstance(llm_tokens, dict):
                    for provider, tokens in llm_tokens.items():
                        if isinstance(tokens, dict):
                            if 'limit' in tokens:
                                await self._chatAgent_dao.update_llm_tokens(provider, tokens['limit'])
                            if 'used' in tokens:
                                await self._chatAgent_dao.update_llm_used_tokens(provider, tokens['used'])
            
            # Save persona configuration
            if 'persona' in config_data:
                persona_data = config_data['persona']
                if isinstance(persona_data, dict):
                    if 'selected_persona' in persona_data:
                        persona_name = persona_data['selected_persona']
                        system_prompt = persona_data.get('system_prompt', f"You are {persona_name}, a helpful AI assistant. Your role is to assist users with their questions and provide accurate, helpful responses.")
                        
                        # If it's a custom persona, create/update it with the custom system prompt
                        if persona_name == 'Custom':
                            # For custom personas, we need to handle them specially
                            # Create or update the custom persona with the provided system prompt
                            await self._chatAgent_dao.update_persona(
                                persona_name='Custom',
                                system_prompt=system_prompt,
                                is_active=True
                            )
                        else:
                            # For predefined personas, just activate them with default system prompt
                            default_system_prompt = f"You are {persona_name}, a helpful AI assistant. Your role is to assist users with their questions and provide accurate, helpful responses."
                            await self._chatAgent_dao.update_persona(
                                persona_name=persona_name,
                                system_prompt=default_system_prompt,
                                is_active=True
                            )
                        
                        logger.info(f"✅ Successfully updated persona: {persona_name}")
            
            logger.info("✅ Chatbot config saved successfully")

        except Exception as e:
            logger.error(f"❌ Error saving chatbot config: {e}")
            raise
