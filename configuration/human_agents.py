"""
Human Agent Management Endpoints
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import logging
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.auth_middleware import get_current_user
from shared.db import get_db_connection
from ..servcie.human_agents_service import HumanAgentsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["human-agents"])


class HumanAgentsRequest(BaseModel):
    emails: List[EmailStr]


class ConfirmAgentRequest(BaseModel):
    token: str


class AgentResponse(BaseModel):
    email: str
    status: str
    confirmation_token: Optional[str] = None


@router.post("/human-agents", response_model=dict)
async def add_human_agents(
    request: HumanAgentsRequest,
    current_user: dict = Depends(get_current_user)
):
    """Add human agents and send confirmation emails."""
    try:
        async with get_db_connection() as conn:
            service = HumanAgentsService(conn)
            result = await service.add_human_agents(request.emails)
            
            return {
                "success": True,
                "message": "Agents processed successfully",
                "results": result["results"]
            }
    except Exception as e:
        logger.error(f"Error adding human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding agents: {str(e)}")


@router.delete("/human-agents/{email}", response_model=dict)
async def remove_human_agent(
    email: str,
    current_user: dict = Depends(get_current_user)
):
    """Remove human agent and send removal notification."""
    try:
        async with get_db_connection() as conn:
            service = HumanAgentsService(conn)
            await service.delete_human_agent(email)
            
            return {
                "success": True,
                "message": "Agent removed successfully"
            }
    except Exception as e:
        logger.error(f"Error removing agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing agent: {str(e)}")

