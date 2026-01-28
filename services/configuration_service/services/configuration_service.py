"""
Configuration Service for Configuration Management
Provides business logic layer between routers and DAO
"""
import logging
from typing import List, Dict, Any, Optional
from services.configuration_service.dao.chatbot_dao import ChatbotDAO
from services.configuration_service.dao.widget_dao import WidgetDAO
from services.configuration_service.dao.performance_dao import PerformanceDAO
from services.configuration_service.dao.auth_dao import AuthDAO
from services.configuration_service.core.database import get_db_connection

logger = logging.getLogger(__name__)

class ConfigurationService:
    """Service layer for configuration operations"""
    
    def __init__(self):
        self._chatbot_dao = None
        self._widget_dao = None
        self._performance_dao = None
        self._auth_dao = None
    
    async def _get_chatbot_dao(self) -> ChatbotDAO:
        """Get ChatbotDAO instance with database connection"""
        if self._chatbot_dao is None:
            async with get_db_connection() as conn:
                self._chatbot_dao = ChatbotDAO(conn)
        return self._chatbot_dao
    
    async def _get_widget_dao(self) -> WidgetDAO:
        """Get WidgetDAO instance with database connection"""
        if self._widget_dao is None:
            async with get_db_connection() as conn:
                self._widget_dao = WidgetDAO(conn)
        return self._widget_dao
    
    async def _get_performance_dao(self) -> PerformanceDAO:
        """Get PerformanceDAO instance with database connection"""
        if self._performance_dao is None:
            async with get_db_connection() as conn:
                self._performance_dao = PerformanceDAO(conn)
        return self._performance_dao
    
    async def _get_auth_dao(self) -> AuthDAO:
        """Get AuthDAO instance with database connection"""
        if self._auth_dao is None:
            async with get_db_connection() as conn:
                self._auth_dao = AuthDAO(conn)
        return self._auth_dao
    
    # Chatbot Configuration Methods
    async def get_metadata(self) -> Optional[Dict[str, Any]]:
        """Get chatbot metadata"""
        try:
            dao = await self._get_chatbot_dao()
            return await dao.get_metadata()
        except Exception as e:
            logger.error(f"Error getting metadata: {e}")
            return None
    
    async def update_metadata(self, **kwargs):
        """Update chatbot metadata"""
        try:
            dao = await self._get_chatbot_dao()
            await dao.update_metadata(**kwargs)
        except Exception as e:
            logger.error(f"Error updating metadata: {e}")
            raise
    
    # Human Agent Management Methods
    async def create_human_agent(self, email: str) -> int:
        """Create a new human agent"""
        try:
            dao = await self._get_chatbot_dao()
            return await dao.create_human_agent(email)
        except Exception as e:
            logger.error(f"Error creating human agent: {e}")
            raise
    
    async def get_all_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        try:
            dao = await self._get_chatbot_dao()
            return await dao.get_all_human_agents()
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            return []
    
    async def delete_human_agent(self, email: str):
        """Delete a human agent"""
        try:
            dao = await self._get_chatbot_dao()
            await dao.delete_human_agent(email)
        except Exception as e:
            logger.error(f"Error deleting human agent: {e}")
            raise
    
    # Widget Configuration Methods
    async def get_widget_config(self) -> Optional[Dict[str, Any]]:
        """Get widget configuration"""
        try:
            dao = await self._get_widget_dao()
            return await dao.get_widget_config()
        except Exception as e:
            logger.error(f"Error getting widget config: {e}")
            return None
    
    async def update_widget_config(self, config_data: Dict[str, Any]):
        """Update widget configuration"""
        try:
            dao = await self._get_widget_dao()
            await dao.update_widget_config(config_data)
        except Exception as e:
            logger.error(f"Error updating widget config: {e}")
            raise
    
    # Performance Metrics Methods
    async def get_total_interactions(self) -> int:
        """Get total interactions"""
        try:
            dao = await self._get_performance_dao()
            return await dao.get_total_interactions() or 0
        except Exception as e:
            logger.error(f"Error getting total interactions: {e}")
            return 0
    
    async def get_total_sessions(self) -> int:
        """Get total sessions"""
        try:
            dao = await self._get_performance_dao()
            return await dao.get_total_sessions() or 0
        except Exception as e:
            logger.error(f"Error getting total sessions: {e}")
            return 0
    
    async def get_active_sessions(self) -> int:
        """Get active sessions"""
        try:
            dao = await self._get_performance_dao()
            return await dao.get_active_sessions() or 0
        except Exception as e:
            logger.error(f"Error getting active sessions: {e}")
            return 0
    
    async def get_average_engagement_time(self) -> Optional[float]:
        """Get average engagement time"""
        try:
            dao = await self._get_performance_dao()
            return await dao.get_average_engagement_time()
        except Exception as e:
            logger.error(f"Error getting average engagement time: {e}")
            return None
    
    # Authentication Methods
    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists"""
        try:
            dao = await self._get_auth_dao()
            return await dao.check_admin_exists(email)
        except Exception as e:
            logger.error(f"Error checking admin exists: {e}")
            return None
    
    async def check_human_agent_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if human agent exists"""
        try:
            dao = await self._get_auth_dao()
            return await dao.check_human_agent_exists(email)
        except Exception as e:
            logger.error(f"Error checking human agent exists: {e}")
            return None

# Singleton instance
configuration_service = ConfigurationService()
