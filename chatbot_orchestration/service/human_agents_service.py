"""
Human Agents Service Layer for Chatbot Orchestration
Provides business logic for human agents management operations
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from shared.logging_config import get_railway_logger

from shared.dao.chat_dao import ChatDAO as SharedChatDAO
from shared.dao.user_dao import UserDAO
from ..dao.chat_dao import ChatDAO as LocalChatDAO

logger = get_railway_logger(__name__)

class AgentResponse(BaseModel):
    email: str
    status: str
    online: Optional[bool] = None

class HumanAgentsService:
    """Service layer for human agents management in chatbot orchestration"""
    
    def __init__(self):
        self.local_chat_dao = LocalChatDAO()  # For orchestration-specific methods
        self.shared_chat_dao = SharedChatDAO()  # For shared chat sessions methods
        self.user_dao = UserDAO()  # For user/agent management methods
    
    async def add_human_agents(self, emails: List[str]) -> Dict[str, Any]:
        """Add multiple human agents"""
        results = []
        for email in emails:
            try:
                await self.user_dao.create_human_agent(email)
                results.append({"email": email, "status": "success"})
                logger.info(f"Human agent {email} added successfully")
            except Exception as e:
                results.append({"email": email, "status": "error", "message": str(e)})
                logger.error(f"Error adding human agent {email}: {e}")
        
        return {"results": results}
    
    async def get_human_agents(self) -> List[AgentResponse]:
        """Get all human agents"""
        try:
            agents = await self.user_dao.get_human_agents()
            return [
                AgentResponse(
                    email=agent.get("email", ""),
                    status="active",
                    online=agent.get("is_online", False)
                )
                for agent in agents
            ]
        except Exception as e:
            logger.error(f"Error fetching human agents: {e}")
            raise
    
    async def delete_human_agent(self, email: str) -> bool:
        """Delete a human agent"""
        try:
            await self.user_dao.remove_human_agent(email)
            logger.info(f"Human agent {email} deleted successfully")
            return True
        except Exception as e:
            logger.error(f"Error deleting human agent {email}: {e}")
            return False
    
    async def get_agent_online_status(self, agent_email: str) -> bool:
        """Check if an agent is online by checking their last activity timestamp."""
        try:
            return await self.shared_chat_dao.get_agent_online_status(agent_email)
        except Exception as e:
            logger.error(f"Error checking agent online status: {e}")
            return False
    
    async def get_online_agents(self) -> List[AgentResponse]:
        """Get all online human agents"""
        try:
            agents = await self.user_dao.get_human_agents()
            return [
                AgentResponse(
                    email=agent.get("email", ""),
                    status="online",
                    online=True
                )
                for agent in agents
            ]
        except Exception as e:
            logger.error(f"Error fetching online agents: {e}")
            raise
