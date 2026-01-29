"""
Human Agents Management Endpoints
All human agent configuration is centralized in the configuration service.
"""
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from configuration.core.logging_config import get_railway_logger

from ..service.configuration_service import configuration_service

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/human-agents", tags=["human-agents"])


class HumanAgentsRequest(BaseModel):
    emails: List[EmailStr]


class AgentResponse(BaseModel):
    email: str
    status: str
    created_at: str = None


@router.get("/admin/human-agents", response_model=dict)
async def get_all_human_agents_admin():
    """Get all human agents - admin endpoint for frontend compatibility."""
    try:
        agents = await configuration_service.get_human_agents()
        
        # Extract just the emails for frontend compatibility
        human_agents = [agent.get("email", "") for agent in agents if agent.get("email")]
        
        return {"human_agents": human_agents}
    except Exception as e:
        logger.error(f"Error fetching human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching agents: {str(e)}")


@router.get("/admin/agents/online", response_model=dict)
async def get_online_agents_admin():
    """Get all online agents - admin endpoint for frontend compatibility."""
    try:
        agents = await configuration_service.get_online_human_agents()
        
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
        logger.error(f"Error fetching online agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching online agents: {str(e)}")


@router.post("/", response_model=dict)
async def add_human_agents(request: HumanAgentsRequest):
    """Add human agents to the system."""
    # Note: Authentication should be handled at the API Gateway level
    try:
        results = []
        
        for email in request.emails:
            try:
                # Check if agent already exists
                existing = await configuration_service.check_human_agent_exists(email)
                if existing:
                    results.append({
                        "email": email,
                        "status": "already_exists",
                        "message": "Human agent already exists"
                    })
                    continue
                
                # Create new human agent
                await configuration_service.create_human_agent(email)
                results.append({
                    "email": email,
                    "status": "created",
                    "message": "Human agent created successfully"
                })
                logger.info(f"Human agent created: {email}")
                
            except Exception as e:
                results.append({
                    "email": email,
                    "status": "error",
                    "message": f"Error creating human agent: {str(e)}"
                })
                logger.error(f"Error creating human agent {email}: {e}")
        
        return {
            "success": True,
            "message": "Human agents processed successfully",
            "results": results
        }
    except Exception as e:
        logger.error(f"Error adding human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding agents: {str(e)}")


@router.get("/", response_model=List[AgentResponse])
async def get_human_agents():
    """Get all human agents."""
    try:
        agents = await configuration_service.get_human_agents()
        
        # Format response
        formatted_agents = []
        for agent in agents:
            formatted_agents.append({
                "email": agent.get("email", ""),
                "status": "active",
                "created_at": agent.get("created_at", "").isoformat() if agent.get("created_at") else None
            })
        
        return formatted_agents
    except Exception as e:
        logger.error(f"Error fetching human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching agents: {str(e)}")


@router.get("/online", response_model=List[AgentResponse])
async def get_online_agents():
    """Get all online human agents."""
    try:
        agent_emails = await configuration_service.get_all_human_agents()
        
        # For now, return all agents as online since we don't have heartbeat tracking
        # In production, this should check actual online status
        online_agents = []
        for email in agent_emails:
            online_agents.append({
                "email": email,
                "status": "online",
                "created_at": None
            })
        
        return online_agents
    except Exception as e:
        logger.error(f"Error fetching online agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching online agents: {str(e)}")


@router.delete("/{email}", response_model=dict)
async def remove_human_agent(email: str):
    """Remove a human agent from the system."""
    try:
        # Check if agent exists
        existing = await configuration_service.check_human_agent_exists(email)
        if not existing:
            raise HTTPException(status_code=404, detail="Human agent not found")
        
        # Remove agent
        await configuration_service.delete_human_agent(email)
        
        return {
            "success": True,
            "message": "Human agent removed successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing agent: {str(e)}")


@router.get("/{email}/status", response_model=dict)
async def get_agent_status(email: str):
    """Get the status of a specific agent."""
    try:
        # Check if agent exists
        existing = await configuration_service.check_human_agent_exists(email)
        if not existing:
            raise HTTPException(status_code=404, detail="Human agent not found")
        
        # For now, return online status since we don't have heartbeat tracking
        # In production, this should check actual online status
        return {
            "email": email,
            "online": True,
            "status": "online"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking agent status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error checking agent status: {str(e)}")
