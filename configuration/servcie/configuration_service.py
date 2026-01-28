"""
Configuration Service for Configuration Management
Provides business logic layer between routers and DAO
"""
import logging
from typing import List, Dict, Any, Optional
from ..dao.chatbot_dao import ChatbotDAO
from ..dao.widget_dao import WidgetDAO
from ..dao.performance_dao import PerformanceDAO
from ..dao.auth_dao import AuthDAO

logger = logging.getLogger(__name__)

class ConfigurationService:
    """Service layer for configuration operations"""
    
    def __init__(self):
        self._chatbot_dao = ChatbotDAO()  # Service manages its own DAO
        self._widget_dao = WidgetDAO()    # Service manages its own DAO
        self._performance_dao = PerformanceDAO()  # Service manages its own DAO
        self._auth_dao = AuthDAO()  # Service manages its own DAO
    
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
    async def create_human_agent(self, email: str) -> int:
        """Create a new human agent"""
        try:
            return await self._chatbot_dao.create_human_agent(email)
        except Exception as e:
            logger.error(f"Error creating human agent: {e}")
            raise
    
    async def get_all_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        try:
            return await self._chatbot_dao.get_all_human_agents()
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            return []
    
    async def delete_human_agent(self, email: str):
        """Delete a human agent"""
        try:
            await self._chatbot_dao.delete_human_agent(email)
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
    
    # Performance Metrics Methods
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

    async def find_human_agent(self, email: str):
        """Find human agent by email"""
        try:
            return await self._chatbot_dao.find_human_agent(email)
        except Exception as e:
            logger.error(f"Error finding human agent: {e}")
            return None

    async def add_human_agent(self, email: str):
        """Add a new human agent"""
        try:
            return await self._chatbot_dao.add_human_agent(email)
        except Exception as e:
            logger.error(f"Error adding human agent: {e}")
            raise

    async def get_all_human_agents(self):
        """Get all human agents"""
        try:
            return await self._chatbot_dao.get_all_human_agents()
        except Exception as e:
            logger.error(f"Error getting all human agents: {e}")
            return []

    async def delete_human_agent(self, email: str):
        """Delete human agent by email"""
        try:
            await self._chatbot_dao.delete_human_agent(email)
        except Exception as e:
            logger.error(f"Error deleting human agent: {e}")
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

            # Build persona dict
            persona_config = {
                "system_prompt": persona['system_prompt'] if persona else "",
                "selected_persona": persona['persona_name'] if persona else "friendly-receptionist"
            }

            # Build final configuration
            data = {
                "admin_user": "GLOBISTAAN",
                "admin_emails": admin_emails_list,
                "admin_password": "**********",
                "human_agents": human_agents_list,
                "hil_enabled": metadata['hil_enabled'] if metadata else True,
                "notifications": notifications,
                "security": security,
                "response_policy": metadata['response_policy'] if metadata else 30,
                "data_management": {
                    "backup_logs": False  # This was removed from old schema, keeping default
                },
                "persona": persona_config,
                "llm_tokens": llm_tokens
            }

            return data
        except Exception as e:
            logger.error(f"Error getting chatbot configuration: {e}")
            raise

    async def request_human_agent(self, session_id: str):
        """Request a human agent for a chat session"""
        try:
            from ..servcie.chat_log_service import ChatLogService
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

# Singleton instance
configuration_service = ConfigurationService()
