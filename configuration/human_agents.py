"""
Human Agent Management Endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import secrets
import hashlib
import logging
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.auth_middleware import get_current_user
from .main import get_db_connection
from dao.auth_dao import AuthDAO

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


def generate_confirmation_token() -> str:
    """Generate a secure confirmation token."""
    return secrets.token_urlsafe(32)


def generate_password() -> str:
    """Generate a secure random password."""
    return secrets.token_urlsafe(16)


def generate_widget_link(agent_id: str) -> str:
    """Generate a unique widget link for the agent."""
    import os
    widget_base_url = os.getenv('WIDGET_BASE_URL', 'https://knowledgebot.vercel.app')
    return f"{widget_base_url}/agent/{agent_id}"

def generate_confirmation_link(token: str) -> str:
    """Generate confirmation link for human agent."""
    import os
    frontend_url = os.getenv('FRONTEND_URL', os.getenv('WIDGET_BASE_URL', 'https://knowledgebot.vercel.app'))
    return f"{frontend_url}/agent/confirm?token={token}"


@router.post("/human-agents", response_model=dict)
async def add_human_agents(request: HumanAgentsRequest):
    """Add human agents and send confirmation emails."""
    try:
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            agents_created = []
            
            for email in request.emails:
                # Check if agent already exists
                existing = await auth_dao.check_human_agent_exists(email)
                
                if existing:
                    logger.info(f"Agent {email} already exists, skipping")
                    continue

                # Create new agent
                agent_id = await auth_dao.create_human_agent(email)

                agents_created.append({
                    "email": email
                })
                logger.info(f"Human agent {email} added directly")
            
            return {
                "success": True,
                "message": "Agents added successfully",
                "agents": agents_created
            }
    except Exception as e:
        logger.error(f"Error adding human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding agents: {str(e)}")


# Human agent confirmation endpoint removed - agents are now activated immediately


@router.delete("/human-agents/{email}", response_model=dict)
async def remove_human_agent(email: str):
    """Remove human agent and send removal notification."""
    try:
        async with get_db_connection() as conn:
            auth_dao = AuthDAO(conn)
            
            # Check if agent exists
            agent = await auth_dao.check_human_agent_exists(email)
            
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            
            # Remove agent
            await auth_dao.remove_human_agent(email)
            
            # Agent removed - no email notification sent
            
            return {
                "success": True,
                "message": "Agent removed successfully"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing agent: {str(e)}")

