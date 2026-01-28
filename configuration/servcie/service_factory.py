"""
Service Factory for creating services with proper DAO injection
Handles all database connections internally
"""
import logging
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class ServiceFactory:
    """Factory for creating service instances with proper DAO injection"""
    
    @staticmethod
    async def create_feedback_service():
        """Create FeedbackService with FeedbackDAO"""
        from ..servcie.feedback_service import FeedbackService
        from ..dao.feedback_dao import FeedbackDAO
        
        async with get_db_connection() as conn:
            feedback_dao = FeedbackDAO(conn)
            return FeedbackService(feedback_dao)
    
    @staticmethod
    async def create_token_usage_service():
        """Create TokenUsageService with TokenDAO"""
        from ..servcie.token_usage_service import TokenUsageService
        from shared.dao.token_dao import TokenDAO
        
        async with get_db_connection() as conn:
            token_dao = TokenDAO(conn)
            return TokenUsageService(token_dao)
    
    @staticmethod
    async def create_token_service():
        """Create TokenService with TokenDAO"""
        from shared.servcie.token_service import TokenService
        from shared.dao.token_dao import TokenDAO
        
        async with get_db_connection() as conn:
            token_dao = TokenDAO(conn)
            return TokenService(token_dao)
    
    @staticmethod
    async def create_notifications_service():
        """Create NotificationsService with NotificationsDAO"""
        from ..servcie.notifications_service import NotificationsService
        from ..dao.notifications_dao import NotificationsDAO
        
        async with get_db_connection() as conn:
            notifications_dao = NotificationsDAO(conn)
            return NotificationsService(notifications_dao)
    
    @staticmethod
    async def create_performance_service():
        """Create PerformanceService with PerformanceDAO"""
        from ..servcie.performance_service import PerformanceService
        from ..dao.performance_dao import PerformanceDAO
        
        async with get_db_connection() as conn:
            performance_dao = PerformanceDAO(conn)
            return PerformanceService(performance_dao)
    
    @staticmethod
    async def create_auth_service():
        """Create AuthService with AuthDAO"""
        from ..servcie.auth_service import AuthService
        from ..dao.auth_dao import AuthDAO
        
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            return AuthService(auth_dao)
