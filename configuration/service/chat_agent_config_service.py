"""
Chat Agent Configuration Service for Chat Agent Management
Provides business logic layer for chat agent configuration operations
"""
from typing import Any, Dict, List, Optional

from shared.otel_logger import get_otel_logger
from shared.email_masking import mask_email
from configuration.dao.chat_agent_config_dao import ChatAgentConfigDAO

logger = get_otel_logger("chat_agent_config_service", "configuration")

class ChatAgentConfigService:
    """Service layer for chat agent configuration operations"""

    def __init__(self):
        self._chatAgent_dao = ChatAgentConfigDAO()
    
    async def get_chatAgent_config(self):
        """Get complete chatbot configuration with all data transformations"""
        try:
            # Fetch database queries sequentially to avoid connection pool exhaustion
            # Sequential approach: reduces peak connection usage from 6 to 1
            # Performance: slightly slower but prevents timeout errors under load
            widget_config = await self._chatAgent_dao.get_widget_config()
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
               
            # Build metadata from widget config (HIL settings)
            metadata = {}
            if widget_config:
                metadata = {
                    "hil_enabled": widget_config.get('hil_enabled', False),
                    "response_policy": widget_config.get('response_policy', 0.5),
                    "hil_disabled_message": widget_config.get('hil_disabled_message', '')
                }
               
            # Build LLM tokens dict using llm_providers table data (show negative values)
            llm_tokens = {}
            for row in llm_rows:
                provider = row['provider_name']
                token_limit = row['token_limit']
                used_tokens = row['token_used']
                # Calculate available tokens (show negative when overused)
                llm_tokens[provider] = {
                    "used": used_tokens,
                    "available": (token_limit - used_tokens),
                    "limit": token_limit
                }
                
                          
            logger.info(f"✅ get_chatAgent_config : LLM tokens constructed from llm_providers table: {llm_tokens}")

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

            # Build response with {id, masked_email} pairs for display + operations
            response = {
                "admin_emails": [{"id": item["id"], "email": mask_email(item["email"])} for item in admin_emails_list],
                "human_agents": [{"id": item["id"], "email": mask_email(item["email"])} for item in human_agents_list],
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
            
            # Prepare unified widget configuration data
            widget_config_data = {}
            
            # Extract widget appearance settings
            widget_fields = [
                'display_name', 'initial_message', 'auto_show_duration', 'keep_showing_suggested',
                'theme', 'primary_color', 'use_primary_for_header', 'chat_bubble_color', 'align_bubble',
                'display_chatbot', 'profile_picture_url', 'chat_icon_url', 'profile_picture_filename',
                'chat_icon_filename', 'profile_zoom', 'chat_icon_zoom', 'profile_position', 'chat_icon_position'
            ]
            
            for field in widget_fields:
                if field in config_data:
                    widget_config_data[field] = config_data[field]
            
            # Extract metadata settings (HIL settings)
            if 'metadata' in config_data:
                metadata = config_data['metadata']
                if isinstance(metadata, dict):
                    if 'hil_enabled' in metadata:
                        widget_config_data['hil_enabled'] = metadata['hil_enabled']
                    if 'response_policy' in metadata:
                        widget_config_data['response_policy'] = metadata['response_policy']
                    if 'hil_disabled_message' in metadata:
                        widget_config_data['hil_disabled_message'] = metadata['hil_disabled_message']
            
            # Update widget configuration in single call
            if widget_config_data:
                logger.info(f"🔍 Calling update_widget_config with: {widget_config_data}")
                await self._chatAgent_dao.update_widget_config(**widget_config_data)
                logger.info("✅ Widget configuration updated successfully")
            else:
                logger.warning("⚠️ No widget configuration data found to update")

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
            
            # Save admin emails if provided - split into existing IDs and new emails
            if 'admin_emails' in config_data:
                admin_entries = config_data['admin_emails']
                if isinstance(admin_entries, list):
                    existing_ids = [item["id"] for item in admin_entries if isinstance(item, dict) and "id" in item]
                    new_emails = [item["email"] for item in admin_entries if isinstance(item, dict) and "id" not in item and "email" in item]
                    logger.info(f"💾 Syncing admins: keep_ids={existing_ids}, new_emails={new_emails}")
                    await self._chatAgent_dao.sync_admins(existing_ids, new_emails)

            # Save human agents if provided - split into existing IDs and new emails
            if 'human_agents' in config_data:
                agent_entries = config_data['human_agents']
                if isinstance(agent_entries, list):
                    existing_ids = [item["id"] for item in agent_entries if isinstance(item, dict) and "id" in item]
                    new_emails = [item["email"] for item in agent_entries if isinstance(item, dict) and "id" not in item and "email" in item]
                    logger.info(f"💾 Syncing human agents: keep_ids={existing_ids}, new_emails={new_emails}")
                    await self._chatAgent_dao.sync_human_agents(existing_ids, new_emails)
            
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
            
            # Clear agent cache in chatbot-orchestration service
            # This ensures the next message will use the updated configuration
            try:
                logger.info("🔄 Clearing agent cache in chatbot-orchestration service...")
                import httpx
                import os
                
                # Get chatbot orchestration service URL from environment
                chatbot_service_url = os.getenv(
                    'CHATBOT_ORCHESTRATION_URL',
                    'http://chatbot-orchestration.railway.internal:8080'
                )
                
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(
                        f"{chatbot_service_url}/internal/clear-agent-cache",
                        timeout=5.0
                    )
                    
                    if response.status_code == 200:
                        logger.info("✅ Agent cache cleared successfully")
                    else:
                        logger.warning(f"⚠️ Failed to clear agent cache: {response.status_code}")
            except Exception as cache_error:
                logger.warning(f"⚠️ Could not clear agent cache: {cache_error}")
                # Don't fail the request if cache clearing fails

        except Exception as e:
            logger.error(f"❌ Error saving chatbot config: {e}")
            raise

    async def get_security_settings(self) -> Dict[str, Any]:
        """Get security settings only"""
        try:
            security_rows = await self._chatAgent_dao.get_security_settings()
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
            llm_rows = await self._chatAgent_dao.get_llm_providers()
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
            persona = await self._chatAgent_dao.get_active_persona()
            all_personas = []

            try:
                all_personas = await self._chatAgent_dao.get_all_personas()
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

    async def get_human_agents(self) -> List[Dict]:
        """Get human agents list with {id, masked_email} for display"""
        try:
            agents = await self._chatAgent_dao.get_human_agents()
            return [{"id": a["id"], "email": mask_email(a["email"])} for a in agents]
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            raise

    async def get_admin_emails(self) -> List[Dict]:
        """Get admin emails list with {id, masked_email} for display"""
        try:
            admins = await self._chatAgent_dao.get_admins()
            return [{"id": a["id"], "email": mask_email(a["email"])} for a in admins]
        except Exception as e:
            logger.error(f"Error getting admin emails: {e}")
            raise

    async def remove_admin(self, user_id: int) -> bool:
        """Remove an admin user by user ID"""
        try:
            result = await self._chatAgent_dao.remove_admin_by_id(user_id)
            logger.info(f"✅ Admin user {user_id} removed successfully")
            return result
        except Exception as e:
            logger.error(f"Error removing admin user {user_id}: {e}")
            raise

    async def remove_human_agent(self, user_id: int) -> bool:
        """Remove a human agent by user ID"""
        try:
            result = await self._chatAgent_dao.remove_human_agent_by_id(user_id)
            logger.info(f"✅ Human agent user {user_id} removed successfully")
            return result
        except Exception as e:
            logger.error(f"Error removing human agent user {user_id}: {e}")
            raise

    async def add_human_agent(self, email: str) -> bool:
        """Add a new human agent by email"""
        try:
            result = await self._chatAgent_dao.add_human_agent(email)
            logger.info(f"✅ Human agent {email} added successfully")
            return result
        except Exception as e:
            logger.error(f"Error adding human agent {email}: {e}")
            raise

    async def add_admin(self, email: str) -> bool:
        """Add a new admin by email"""
        try:
            result = await self._chatAgent_dao.add_admin(email)
            logger.info(f"✅ Admin {email} added successfully")
            return result
        except Exception as e:
            logger.error(f"Error adding admin {email}: {e}")
            raise
