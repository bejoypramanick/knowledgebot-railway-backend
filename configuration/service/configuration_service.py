"""
Configuration Service for Configuration Management
Provides business logic layer between routers and DAO
"""
from typing import Any, Dict, List, Optional

from configuration.core.logging_config import get_railway_logger

from ..dao.auth_dao import AuthDAO
from ..dao.chatbot_dao import ChatbotDAO
from ..dao.performance_dao import PerformanceDAO
from ..dao.widget_dao import WidgetDAO

logger = get_railway_logger(__name__)

class ConfigurationService:
    """Service layer for configuration operations"""
    
    def __init__(self):
        self._chatbot_dao = ChatbotDAO()  # Service manages its own DAO
        self._auth_dao = AuthDAO()  # Service manages its own DAO
        self._widget_dao = WidgetDAO()    # Service manages its own DAO
        self._performance_dao = PerformanceDAO()  # Service manages its own DAO
    
    # Chatbot Configuration Methods
    async def get_metadata(self) -> Optional[Dict[str, Any]]:
        """Get chatbot metadata"""
        try:
            return await self._chatbot_dao.get_metadata()
        except Exception as e:
            logger.error(f"Error getting metadata: {e}")
            return None
    
    async def update_metadata(self, **kwargs):
        """Update chatbot metadata"""
        try:
            await self._chatbot_dao.update_metadata(**kwargs)
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
            agents = await self._auth_dao.get_available_agents()
            return [agent['email'] for agent in agents]
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
    
    # Widget Configuration Methods
    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get widget configuration"""
        try:
            return await self._widget_dao.get_widget_config()
        except Exception as e:
            logger.error(f"Error getting widget config: {e}")
            return None
    
    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration"""
        try:
            await self._widget_dao.update_widget_config(config_data)
        except Exception as e:
            logger.error(f"Error updating widget config: {e}")
            raise
    
    async def get_widget_config_with_transform(self):
        """Get complete widget configuration with all data transformations"""
        try:
            # Get main widget configuration
            row = await self._widget_dao.get_widget_config()
            
            # Get suggested messages
            suggested_messages = await self._widget_dao.get_suggested_messages()
            
            return {
                **row,
                'suggested_messages': suggested_messages
            }
        except Exception as e:
            logger.error(f"Error getting widget config with transform: {e}")
            return None

    async def get_total_interactions(self) -> int:
        """Get total interactions"""
        try:
            return await self._performance_dao.get_total_interactions() or 0
        except Exception as e:
            logger.error(f"Error getting total interactions: {e}")
            return 0
    
    async def get_total_sessions(self) -> int:
        """Get total sessions"""
        try:
            return await self._performance_dao.get_total_sessions() or 0
        except Exception as e:
            logger.error(f"Error getting total sessions: {e}")
            return 0
    
    async def get_active_sessions(self) -> int:
        """Get active sessions"""
        try:
            return await self._performance_dao.get_active_sessions() or 0
        except Exception as e:
            logger.error(f"Error getting active sessions: {e}")
            return 0
    
    async def get_average_engagement_time(self) -> Optional[float]:
        """Get average engagement time"""
        try:
            return await self._performance_dao.get_average_engagement_time()
        except Exception as e:
            logger.error(f"Error getting average engagement time: {e}")
            return None
    
    # Authentication Methods
    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists"""
        try:
            return await self._auth_dao.check_admin_exists(email)
        except Exception as e:
            logger.error(f"Error checking admin exists: {e}")
            return None
    
    async def check_human_agent_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if human agent exists"""
        try:
            return await self._auth_dao.check_human_agent_exists(email)
        except Exception as e:
            logger.error(f"Error checking human agent exists: {e}")
            return None
    
    # Widget Configuration Methods
    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get widget configuration"""
        try:
            return await self._widget_dao.get_widget_config()
        except Exception as e:
            logger.error(f"Error getting widget config: {e}")
            return None
    
    async def get_suggested_messages(self) -> List[Dict[str, Any]]:
        """Get suggested messages"""
        try:
            return await self._widget_dao.get_suggested_messages()
        except Exception as e:
            logger.error(f"Error getting suggested messages: {e}")
            return []
    
    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration"""
        try:
            await self._widget_dao.update_widget_config(config_data)
        except Exception as e:
            logger.error(f"Error updating widget config: {e}")
            raise
    
    # Chatbot Configuration Methods
    async def get_notification_settings(self) -> List[Dict[str, Any]]:
        """Get notification settings"""
        try:
            return await self._chatbot_dao.get_notification_settings()
        except Exception as e:
            logger.error(f"Error getting notification settings: {e}")
            return []
    
    async def get_security_settings(self) -> List[Dict[str, Any]]:
        """Get security settings"""
        try:
            return await self._chatbot_dao.get_security_settings()
        except Exception as e:
            logger.error(f"Error getting security settings: {e}")
            return []
    
    async def get_llm_providers(self) -> List[Dict[str, Any]]:
        """Get LLM providers"""
        try:
            return await self._chatbot_dao.get_llm_providers()
        except Exception as e:
            logger.error(f"Error getting LLM providers: {e}")
            return []
    
    async def get_active_persona(self) -> Optional[Dict[str, Any]]:
        """Get active persona"""
        try:
            return await self._chatbot_dao.get_active_persona()
        except Exception as e:
            logger.error(f"Error getting active persona: {e}")
            return None
    
    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get human agents"""
        try:
            return await self._chatbot_dao.get_human_agents()
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            return []
    
    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get admins"""
        try:
            return await self._chatbot_dao.get_admins()
        except Exception as e:
            logger.error(f"Error getting admins: {e}")
            return []

    async def log_audit_change(self, user_email: str, action: str, details: dict, ip_address: str = None):
        """Log configuration change for audit purposes"""
        try:
            # This should be implemented in the DAO layer
            # For now, just log the change
            logger.info(f"Configuration change logged: {action} by {user_email}")
        except Exception as e:
            logger.error(f"Failed to log configuration change: {e}")

    async def clear_suggested_messages(self):
        """Clear all suggested messages"""
        try:
            await self._widget_dao.clear_suggested_messages()
        except Exception as e:
            logger.error(f"Error clearing suggested messages: {e}")
            raise

    async def add_suggested_message(self, message: str, index: int):
        """Add a suggested message"""
        try:
            await self._widget_dao.add_suggested_message(message, index)
        except Exception as e:
            logger.error(f"Error adding suggested message: {e}")
            raise

    async def upsert_configuration_metadata(self, meta_updates: dict):
        """Upsert configuration metadata"""
        try:
            await self._chatbot_dao.upsert_configuration_metadata(meta_updates)
        except Exception as e:
            logger.error(f"Error upserting configuration metadata: {e}")
            raise

    async def upsert_notification_setting_with_desc(self, setting_name: str, value: bool, description: str):
        """Upsert notification setting with description"""
        try:
            await self._chatbot_dao.upsert_notification_setting_with_desc(setting_name, value, description)
        except Exception as e:
            logger.error(f"Error upserting notification setting: {e}")
            raise

    async def upsert_security_setting_with_desc(self, setting_name: str, value: str, setting_type: str, description: str):
        """Upsert security setting with description"""
        try:
            await self._chatbot_dao.upsert_security_setting_with_desc(setting_name, value, setting_type, description)
        except Exception as e:
            logger.error(f"Error upserting security setting: {e}")
            raise

    async def upsert_persona(self, persona_name: str, system_prompt: str):
        """Upsert persona configuration"""
        try:
            await self._chatbot_dao.upsert_persona(persona_name, system_prompt)
        except Exception as e:
            logger.error(f"Error upserting persona: {e}")
            raise

    async def sync_admin_emails(self, admin_emails: List[str]) -> Dict[str, List[str]]:
        """Sync admin emails by comparing database with UI request"""
        try:
            return await self._chatbot_dao.sync_admin_emails(admin_emails)
        except Exception as e:
            logger.error(f"Error syncing admin emails: {e}")
            raise

    async def sync_human_agent_emails(self, human_agent_emails: List[str]) -> Dict[str, List[str]]:
        """Sync human agent emails by comparing database with UI request"""
        try:
            return await self._chatbot_dao.sync_human_agent_emails(human_agent_emails)
        except Exception as e:
            logger.error(f"Error syncing human agent emails: {e}")
            raise

    async def update_llm_tokens(self, provider: str, token_limit: int):
        """Update LLM token limit"""
        try:
            await self._chatbot_dao.update_llm_tokens(provider, token_limit)
        except Exception as e:
            logger.error(f"Error updating LLM tokens: {e}")
            raise

    async def update_llm_used_tokens(self, provider: str, token_used: int):
        """Update LLM used tokens"""
        try:
            await self._chatbot_dao.update_llm_used_tokens(provider, token_used)
        except Exception as e:
            logger.error(f"Error updating LLM used tokens: {e}")
            raise

    async def get_chatbot_config(self):
        """Get complete chatbot configuration with all data transformations"""
        try:
            # Get all raw data
            metadata = await self.get_metadata()
            notification_rows = await self.get_notification_settings()
            security_rows = await self.get_security_settings()
            llm_rows = await self.get_llm_providers()
            persona = await self.get_active_persona()
            human_agents_list = await self.get_human_agents()
            admin_emails_list = await self.get_admins()

            # Build notification settings dict
            notifications = {
                "user_interactions_enabled": False,
                "error_alerts_enabled": False,
                "feedback_requests_enabled": True
            }
            for row in notification_rows:
                if row['setting_name'] == 'user_interactions_enabled':
                    notifications['user_interactions_enabled'] = row['is_enabled']
                elif row['setting_name'] == 'error_alerts_enabled':
                    notifications['error_alerts_enabled'] = row['is_enabled']
                elif row['setting_name'] == 'feedback_requests_enabled':
                    notifications['feedback_requests_enabled'] = row['is_enabled']

            # Build security settings dict
            security = {
                "response_timeout": 30,
                "remove_pii": False,
                "restrict_config": False
            }
            for row in security_rows:
                if row['setting_name'] == 'response_timeout':
                    security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30
                elif row['setting_name'] == 'remove_pii':
                    security['remove_pii'] = row['setting_value'].lower() == 'true' if row['setting_type'] == 'boolean' else False
                elif row['setting_name'] == 'restrict_config':
                    security['restrict_config'] = row['setting_value'].lower() == 'true' if row['setting_type'] == 'boolean' else False

            # Build LLM tokens dict
            llm_tokens = {
                "gemini": {"used": 0, "available": 20000, "limit": 20000}
            }
            for row in llm_rows:
                provider = row['provider_name']
                if provider == 'gemini':
                    llm_tokens['gemini'] = {
                        "used": row['token_used'] or 0,
                        "available": (row['token_limit'] or 0) - (row['token_used'] or 0),
                        "limit": row['token_limit'] or 0
                    }

            # Initialize persona config with active persona
            persona_config = {
                "system_prompt": persona.get('system_prompt', '') if persona else "",
                "selected_persona": persona.get('persona_name', 'KnowledgeBot') if persona else "KnowledgeBot"
            }

            # Get all available personas (with fallback)
            try:
                from .personas_service import PersonasService
                personas_service = PersonasService()
                personas_response = await personas_service.get_personas()
                all_personas = personas_response.get('data', {}).get('all_personas', [])
                
                # Select the first persona (most recent) as default if no active persona is set
                if not persona and all_personas:
                    first_persona = all_personas[0]
                    persona_config = {
                        "system_prompt": first_persona.get('system_prompt', ''),
                        "selected_persona": first_persona.get('persona_name', 'KnowledgeBot')
                    }
                    
            except Exception as e:
                logger.warning(f"Could not fetch personas from database, using fallback: {e}")
                all_personas = [{
                    'persona_name': 'KnowledgeBot',
                    'persona_description': 'A helpful AI assistant for knowledge management',
                    'is_active': True,
                    'system_prompt': 'You are KnowledgeBot, a helpful AI assistant specialized in knowledge management. Your role is to help users find information, answer questions based on available documents, and provide clear, accurate responses. Be friendly, professional, and always try to be helpful.'
                }]

            # Build final configuration
            data = {
                "admin_user": "GLOBISTAAN",
                "admin_emails": admin_emails_list,
                "human_agents": human_agents_list,
                "hil_enabled": metadata['hil_enabled'] if metadata else True,
                "notifications": notifications,
                "security": security,
                "response_policy": metadata['response_policy'] if metadata else 30,
                "data_management": {
                    "backup_logs": False  # This was removed from old schema, keeping default
                },
                "persona": persona_config,
                "available_personas": all_personas,
                "llm_tokens": llm_tokens
            }

            return data
        except Exception as e:
            logger.error(f"Error getting chatbot configuration: {e}")
            raise

    async def request_human_agent(self, session_id: str):
        """Request a human agent for a chat session"""
        try:
            from ..service.chat_log_service import ChatLogService
            from ..utils.sse_manager import connection_manager
            
            chat_service = ChatLogService(connection_manager)
            assigned_agent = await chat_service.request_human_agent(session_id)
            
            if assigned_agent:
                return {
                    "status": "assigned",
                    "agent": assigned_agent
                }
            else:
                return {
                    "status": "no_agents_available",
                    "message": "No human agents available"
                }
        except Exception as e:
            logger.error(f"Error requesting human agent: {e}")
            raise

    async def get_widget_config_with_transform(self):
        """Get complete widget configuration with all data transformations"""
        try:
            # Get main widget configuration
            row = await self._widget_dao.get_widget_config()

            # Get suggested messages
            suggested_messages = await self._widget_dao.get_suggested_messages()

            if not row:
                # Return default configuration
                data = {
                    "display_name": "GLOBISTAAN",
                    "initial_message": "Hi! What can I help you with?",
                    "auto_show_duration": 4,
                    "suggested_messages": [],
                    "keep_showing_suggested": True,
                    "theme": "light",
                    "primary_color": "#3B81F6",
                    "use_primary_for_header": True,
                    "chat_bubble_color": "#3B81F6",
                    "align_bubble": "right",
                    "display_chatbot": True,
                    "profile_picture_url": None,
                    "chat_icon_url": None,
                    "profile_zoom": 1.0,
                    "chat_icon_zoom": 1.0,
                    "profile_position": {"x": 0, "y": 0},
                    "chat_icon_position": {"x": 0, "y": 0}
                }
                return data

            # Build data object
            data = {
                "display_name": row["display_name"],
                "initial_message": row["initial_message"],
                "auto_show_duration": row["auto_show_duration"],
                "suggested_messages": suggested_messages,
                "keep_showing_suggested": row["keep_showing_suggested"],
                "theme": row["theme"],
                "primary_color": row["primary_color"],
                "use_primary_for_header": row["use_primary_for_header"],
                "chat_bubble_color": row["chat_bubble_color"],
                "align_bubble": row["align_bubble"],
                "display_chatbot": row["display_chatbot"] if row["display_chatbot"] is not None else True,
                "profile_picture_url": row["profile_picture_url"],
                "chat_icon_url": row["chat_icon_url"],
            }
            
            data["profile_zoom"] = float(row.get("profile_zoom", 1.0)) if row.get("profile_zoom") is not None else 1.0
            data["chat_icon_zoom"] = float(row.get("chat_icon_zoom", 1.0)) if row.get("chat_icon_zoom") is not None else 1.0
            data["profile_position"] = row.get("profile_position") if isinstance(row.get("profile_position"), dict) else {"x": 0, "y": 0}
            data["chat_icon_position"] = row.get("chat_icon_position") if isinstance(row.get("chat_icon_position"), dict) else {"x": 0, "y": 0}
            
            if "profile_picture_filename" in row:
                data["profile_picture_filename"] = row.get("profile_picture_filename")
            if "chat_icon_filename" in row:
                data["chat_icon_filename"] = row.get("chat_icon_filename")

            return data
        except Exception as e:
            logger.error(f"Error getting widget configuration: {e}")
            raise

    async def activate_persona(self, persona_name: str) -> bool:
        """Activate a specific persona by deactivating all others and activating the selected one."""
        try:
            # Use a default system prompt for the persona
            # In a real implementation, you might want to fetch this from a personas table
            default_system_prompt = f"You are {persona_name}, a helpful AI assistant. Your role is to assist users with their questions and provide accurate, helpful responses."
            
            # Use the DAO method to activate the persona
            await self._chatbot_dao.upsert_persona(
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
            
            # Update metadata if provided
            if 'display_name' in config_data or 'description' in config_data or 'response_policy' in config_data:
                metadata_updates = {}
                if 'display_name' in config_data:
                    metadata_updates['display_name'] = config_data['display_name']
                    logger.info(f"🔍 {correlation_prefix}Updating display_name: {config_data['display_name']}")
                if 'description' in config_data:
                    metadata_updates['description'] = config_data['description']
                    logger.info(f"🔍 {correlation_prefix}Updating description: {config_data['description']}")
                if 'response_policy' in config_data:
                    metadata_updates['response_policy'] = config_data['response_policy']
                    logger.info(f"🔍 UPDATING RESPONSE_POLICY: {config_data['response_policy']}")
                
                logger.info(f"🔍 Calling update_metadata with: {metadata_updates}")
                await self.update_metadata(**metadata_updates)
                logger.info(f"✅ update_metadata completed successfully")
            else:
                logger.info(f"🔍 No metadata updates needed - checking keys: display_name={config_data.get('display_name')}, description={config_data.get('description')}, response_policy={config_data.get('response_policy')}")
            
            # Update admin emails if provided
            if 'admin_emails' in config_data and config_data['admin_emails']:
                await self.sync_admin_emails(config_data['admin_emails'])
            
            # Update human agents if provided
            if 'human_agents' in config_data and config_data['human_agents']:
                await self.sync_human_agent_emails(config_data['human_agents'])
            
            # Update persona if provided
            if 'persona' in config_data and 'selected_persona' in config_data['persona']:
                await self.activate_persona(config_data['persona']['selected_persona'])
            
            # Update notifications if provided
            if 'notifications' in config_data:
                notifications = config_data['notifications']
                if isinstance(notifications, dict):
                    if 'user_interactions_enabled' in notifications:
                        await self._chatbot_dao.upsert_notification_setting(
                            'user_interactions_enabled', 
                            notifications['user_interactions_enabled']
                        )
                    if 'error_alerts_enabled' in notifications:
                        await self._chatbot_dao.upsert_notification_setting(
                            'error_alerts_enabled', 
                            notifications['error_alerts_enabled']
                        )
                    if 'feedback_requests_enabled' in notifications:
                        await self._chatbot_dao.upsert_notification_setting(
                            'feedback_requests_enabled', 
                            notifications['feedback_requests_enabled']
                        )
            
            # Update security if provided
            if 'security' in config_data:
                security = config_data['security']
                if isinstance(security, dict):
                    if 'response_timeout' in security:
                        await self._chatbot_dao.upsert_security_setting(
                            'response_timeout', 
                            str(security['response_timeout']), 
                            'integer'
                        )
                    if 'remove_pii' in security:
                        await self._chatbot_dao.upsert_security_setting(
                            'remove_pii', 
                            str(security['remove_pii']).lower(), 
                            'boolean'
                        )
                    if 'restrict_config' in security:
                        await self._chatbot_dao.upsert_security_setting(
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
            
            logger.info("✅ Chatbot config saved successfully")
            
        except Exception as e:
            logger.error(f"❌ Error saving chatbot config: {e}")
            raise

# Singleton instance
configuration_service = ConfigurationService()
