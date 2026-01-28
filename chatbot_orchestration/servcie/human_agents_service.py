"""
Human Agents Service Layer for Chatbot Orchestration
Provides business logic for human agent management operations
"""
import logging
from typing import List, Optional, Dict, Any
from shared.db import get_db_connection
from ..dao.chat_dao import ChatDAO

logger = logging.getLogger(__name__)

class HumanAgentsService:
    """Service layer for human agents management in chatbot orchestration"""
    
    @classmethod
    async def add_human_agents(cls, emails: List[str]) -> Dict[str, Any]:
        """Add multiple human agents"""
        results = []
        async with get_db_connection() as conn:
            chat_dao = ChatDAO(conn)
            for email in emails:
                try:
                    await chat_dao.add_human_agent(email)
                    results.append({"email": email, "status": "success"})
                    logger.info(f"Human agent {email} added successfully")
                except Exception as e:
                    logger.error(f"Error adding human agent {email}: {e}")
                    results.append({"email": email, "status": "error", "error": str(e)})
        
        return {"results": results}
    
    @classmethod
    async def get_human_agents(cls) -> List[Dict[str, Any]]:
        """Get all human agents"""
        async with get_db_connection() as conn:
            chat_dao = ChatDAO(conn)
            try:
                return await chat_dao.get_human_agents()
            except Exception as e:
                logger.error(f"Error fetching human agents: {e}")
                raise
    
    @classmethod
    async def delete_human_agent(cls, email: str) -> bool:
        """Delete a human agent"""
        async with get_db_connection() as conn:
            chat_dao = ChatDAO(conn)
            try:
                await chat_dao.delete_human_agent(email)
                logger.info(f"Human agent {email} deleted successfully")
                return True
            except Exception as e:
                logger.error(f"Error deleting human agent {email}: {e}")
                raise
    
    @classmethod
    async def get_agent_online_status(cls, agent_email: str) -> bool:
        """Check if an agent is online by checking their last activity timestamp."""
        async with get_db_connection() as conn:
            chat_dao = ChatDAO(conn)
            try:
                return await chat_dao.get_agent_online_status(agent_email)
            except Exception as e:
                logger.error(f"Error checking agent online status: {e}")
                return False
    
    @classmethod
    async def get_online_agents(cls) -> List[Dict[str, Any]]:
        """Get all online human agents"""
        async with get_db_connection() as conn:
            chat_dao = ChatDAO(conn)
            try:
                return await chat_dao.get_online_agents()
            except Exception as e:
                logger.error(f"Error fetching online agents: {e}")
                raise
