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

# Singleton instance
configuration_service = ConfigurationService()
