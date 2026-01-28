"""
Human Agents Management Endpoints for Chatbot Orchestration
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from shared.auth_middleware import get_current_user
from shared.logging_config import get_railway_logger

from ..service.human_agents_service import AgentResponse, HumanAgentsService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/human-agents", tags=["human-agents"])


class HumanAgentsRequest(BaseModel):
    emails: List[EmailStr]


@router.post("/", response_model=dict)
async def add_human_agents(
    request: HumanAgentsRequest,
    current_user: dict = Depends(get_current_user)
):
    """Add human agents to the system."""
    try:
        service = HumanAgentsService()  # Service manages its own DAO
        result = await service.add_human_agents(request.emails)
        
        return {
            "success": True,
            "message": "Agents processed successfully",
            "results": result["results"]
        }
    except Exception as e:
        logger.error(f"Error adding human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding agents: {str(e)}")


@router.get("/", response_model=List[AgentResponse])
async def get_human_agents(
    current_user: dict = Depends(get_current_user)
):
    """Get all human agents."""
    try:
        service = HumanAgentsService()  # Service manages its own DAO
        agents = await service.get_human_agents()
        return agents  # Service returns properly formatted response
    except Exception as e:
        logger.error(f"Error fetching human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching agents: {str(e)}")


@router.get("/online", response_model=List[AgentResponse])
async def get_online_agents(
    current_user: dict = Depends(get_current_user)
):
    """Get all online human agents."""
    try:
        service = HumanAgentsService()  # Service manages its own DAO
        agents = await service.get_online_agents()
        return agents  # Service returns properly formatted response
    except Exception as e:
        logger.error(f"Error fetching online agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching agents: {str(e)}")


@router.delete("/{email}", response_model=dict)
async def remove_human_agent(
    email: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove a human agent from the system."""
    try:
        service = HumanAgentsService()  # Service manages its own DAO
        await service.delete_human_agent(email)
        
        return {
            "success": True,
            "message": "Agent removed successfully"
        }
    except Exception as e:
        logger.error(f"Error removing agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing agent: {str(e)}")


@router.get("/{email}/status", response_model=dict)
async def get_agent_status(
    email: str,
    current_user: dict = Depends(get_current_user)
):
    """Get the online status of a specific agent."""
    try:
        service = HumanAgentsService()  # Service manages its own DAO
        is_online = await service.get_agent_online_status(email)
        
        return {
            "email": email,
            "online": is_online,
            "status": "online" if is_online else "offline"
        }
    except Exception as e:
        logger.error(f"Error checking agent status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error checking agent status: {str(e)}")
