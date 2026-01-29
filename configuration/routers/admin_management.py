"""
Admin Management Endpoints
Handles admin user creation, verification, and role management.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from configuration.core.logging_config import get_railway_logger
from configuration.core.auth_middleware import require_admin, get_user_from_token

from ..service.auth_service import AuthService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-management"])


@router.get("/user-role/{email}", response_model=dict)
@require_admin()
async def get_user_role(request, email: str):
    """Get user roles (admin, human_agent, or user) for a given email."""
    try:
        service = AuthService()  # Service manages its own DAO
        return await service.get_user_role(email)
    except Exception as e:
        logger.error(f"Error getting user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user role: {str(e)}")


@router.get("/agents/online", response_model=dict)
async def get_online_agents():
    """Get all online human agents."""
    try:
        from ..service.chat_log_service import ChatLogService
        service = ChatLogService()
        agents = await service.get_online_human_agents()
        
        # Format for frontend compatibility
        formatted_agents = []
        for agent in agents:
            formatted_agents.append({
                "email": agent.get("email", ""),
                "role": "human_agent",
                "is_online": True,
                "active_sessions": 0  # TODO: Get actual session count
            })
        
        return {"agents": formatted_agents}
    except Exception as e:
        logger.error(f"Error getting online agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting online agents: {str(e)}")


@router.get("/human-agents", response_model=dict)
async def get_all_human_agents():
    """Get all human agents - admin endpoint for frontend compatibility."""
    try:
        from ..service.configuration_service import configuration_service
        agents = await configuration_service.get_human_agents()
        
        # Extract just the emails for frontend compatibility
        human_agents = [agent.get("email", "") for agent in agents if agent.get("email")]
        
        return {"human_agents": human_agents}
    except Exception as e:
        logger.error(f"Error fetching human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching agents: {str(e)}")
