"""
Chat Agent Configuration Service for Chat Agent Management
Provides business logic layer for chat agent configuration operations
"""
from typing import Any, Dict, List, Optional

from configuration.core.otel_logger import get_otel_logger
from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO
from configuration.dao.auth_dao import AuthDAO
from configuration.dao.token_dao import TokenDAO

logger = get_otel_logger("chat_agent_config_service", "configuration")

class ChatAgentConfigService:
    """Service layer for chat agent configuration operations"""

    def __init__(self):
        self._chatAgent_dao = ChatAgentConfigDAO()
        self._auth_dao = AuthDAO()
        self._token_dao = TokenDAO()
    
    async def get_metadata(self) -> Optional[Dict[str, Any]]:
        """Get chatbot metadata"""
        try:
            return await self._chatAgent_dao.get_metadata()
        except Exception as e:
            logger.error(f"Error getting metadata: {e}")
            return None
    
    async def update_metadata(self, **kwargs):
        """Update chatbot metadata"""
        try:
            await self._chatAgent_dao.update_metadata(**kwargs)
        except Exception as e:
            logger.error(f"Error updating metadata: {e}")
            raise
    
    # Human Agent Management Methods
    async def create_human_agent(self, email: str) -> str:
        """Create a new human agent"""
        try:
            return await self._auth_dao.create_human_agent(email)
        except Exception as e:
            logger.error(f"Error creating human agent: {e}")
            raise
    
    async def get_all_human_agents(self) -> List[str]:
        """Get all human agents"""
        try:
            # Use auth_dao to get human agents since user_dao doesn't exist locally
            return await self._auth_dao.get_human_agents()
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            return []
    
    async def delete_human_agent(self, email: str):
        """Delete a human agent"""
        try:
            await self._auth_dao.remove_human_agent(email)
        except Exception as e:
            logger.error(f"Error deleting human agent: {e}")
            raise

    # Chatbot Configuration Methods

    async def sync_admin_emails(self, admin_emails: List[str]) -> Dict[str, List[str]]:
        """Sync admin emails by comparing database with UI request"""
        try:
            return await self._chatAgent_dao.sync_admin_emails(admin_emails)
        except Exception as e:
            logger.error(f"Error syncing admin emails: {e}")
            raise

    async def sync_human_agent_emails(self, human_agent_emails: List[str]) -> Dict[str, List[str]]:
        """Sync human agent emails by comparing database with UI request"""
        try:
            return await self._chatAgent_dao.sync_human_agent_emails(human_agent_emails)
        except Exception as e:
            logger.error(f"Error syncing human agent emails: {e}")
            raise

    async def update_llm_tokens(self, provider: str, token_limit: int):
        """Update LLM token limit"""
        try:
            await self._chatAgent_dao.update_llm_tokens(provider, token_limit)
        except Exception as e:
            logger.error(f"Error updating LLM tokens: {e}")
            raise

    async def update_llm_used_tokens(self, provider: str, token_used: int):
        """Update LLM used tokens"""
        try:
            await self._chatAgent_dao.update_llm_used_tokens(provider, token_used)
        except Exception as e:
            logger.error(f"Error updating LLM used tokens: {e}")
            raise

    async def get_chatAgent_config(self):
        """Get complete chatbot configuration with all data transformations"""
        try:
            # Get all raw data
            metadata = await self.get_metadata()
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
               
            # Build LLM tokens dict using actual token usage from token_usage_log
            llm_tokens = {
                "gemini": {"used": 0, "available": 20000, "limit": 20000}
            }
            
            # Get actual token usage from token_usage_log table
            try:
                gemini_usage = await self._token_dao.get_gemini_usage()
                used_tokens = gemini_usage.get("total_tokens", 0)
                limit_tokens = 20000  # Default limit
                available_tokens = max(0, limit_tokens - used_tokens)
                
                llm_tokens['gemini'] = {
                    "used": used_tokens,
                    "available": available_tokens,
                    "limit": limit_tokens
                }
                logger.info(f"✅ Actual token usage calculated: used={used_tokens}, available={available_tokens}")
            except Exception as e:
                logger.error(f"❌ Error calculating actual token usage: {e}")
                # Fallback to static values if calculation fails
                logger.info("⚠️ Using fallback static token values")

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

    async def request_human_agent(self, session_id: str):
        """Request a human agent for a chat session"""
        try:
            from ..service.chat_log_service import ChatLogService
            chat_log_service = ChatLogService()
            
            # Get all human agents
            human_agents = await self.get_all_human_agents()
            
            if not human_agents:
                raise ValueError("No human agents available")
            
            # For now, assign to the first available human agent
            # In a real implementation, you might want to implement load balancing
            assigned_agent = human_agents[0]
            
            # Update the chat session with the assigned human agent
            await chat_log_service.assign_human_agent(session_id, assigned_agent)
            
            logger.info(f"✅ Human agent {assigned_agent} assigned to session {session_id}")
            return assigned_agent
            
        except Exception as e:
            logger.error(f"Error requesting human agent: {e}")
            raise

    async def activate_persona(self, persona_name: str) -> bool:
        """Activate a specific persona by deactivating all others and activating the selected one."""
        try:
            # Use a default system prompt for the persona
            # In a real implementation, you might want to fetch this from a personas table
            default_system_prompt = f"You are {persona_name}, a helpful AI assistant. Your role is to assist users with their questions and provide accurate, helpful responses."
            
            # Use the DAO method to activate the persona
            await self._chatAgent_dao.update_persona(
                persona_name=persona_name,
                system_prompt=default_system_prompt,
                is_active=True
            )
            
            logger.info(f"✅ Successfully activated persona: {persona_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error activating persona '{persona_name}': {e}")
            raise

    async def save_chatbot_config(self, config_data: Dict[str, Any]):
        """Save complete chatbot configuration"""
        try:
            logger.info(f"🔍 Saving chatbot config: {config_data}")
            
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
            
            # Update LLM tokens if provided
            if 'llm_tokens' in config_data:
                llm_tokens = config_data['llm_tokens']
                for provider, tokens in llm_tokens.items():
                    if 'limit' in tokens:
                        await self.update_llm_tokens(provider, tokens['limit'])
                    if 'used' in tokens:
                        await self.update_llm_used_tokens(provider, tokens['used'])
            
            # Save persona configuration
            if 'persona' in config_data:
                persona_data = config_data['persona']
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
                        # For predefined personas, just activate them
                        await self.activate_persona(persona_name)
                    
                    logger.info(f"✅ Successfully updated persona: {persona_name}")
            
            logger.info("✅ Chatbot config saved successfully")

        except Exception as e:
            logger.error(f"❌ Error saving chatbot config: {e}")
            raise
