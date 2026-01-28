"""
Human Agents Service Layer
Provides business logic for human agent management operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.auth_dao import AuthDAO

logger = logging.getLogger(__name__)

class HumanAgentsService:
    """Service layer for human agents management"""
    
    def __init__(self, connection):
        self.auth_dao = AuthDAO(connection)
    
    async def add_human_agents(self, emails: List[str]) -> Dict[str, Any]:
        """Add multiple human agents"""
        results = []
        for email in emails:
            try:
                await self.auth_dao.add_human_agent(email)
                results.append({"email": email, "status": "success"})
                logger.info(f"Human agent {email} added successfully")
            except Exception as e:
                logger.error(f"Error adding human agent {email}: {e}")
                results.append({"email": email, "status": "error", "error": str(e)})
        
        return {"results": results}
    
    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        try:
            return await self.auth_dao.get_human_agents()
        except Exception as e:
            logger.error(f"Error fetching human agents: {e}")
            raise
    
    async def delete_human_agent(self, email: str) -> bool:
        """Delete a human agent"""
        try:
            await self.auth_dao.delete_human_agent(email)
            logger.info(f"Human agent {email} deleted successfully")
            return True
        except Exception as e:
            logger.error(f"Error deleting human agent {email}: {e}")
            raise
