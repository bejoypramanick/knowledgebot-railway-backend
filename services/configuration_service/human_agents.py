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
from shared.db import railway_db
from shared.email_service import create_email_service

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


def generate_widget_link(agent_id: str, email_service) -> str:
    """Generate a unique widget link for the agent."""
    widget_base_url = email_service.widget_base_url
    return f"{widget_base_url}/agent/{agent_id}"

def generate_confirmation_link(token: str) -> str:
    """Generate confirmation link for human agent."""
    import os
    frontend_url = os.getenv('FRONTEND_URL', os.getenv('WIDGET_BASE_URL', 'https://knowledgebot.vercel.app'))
    return f"{frontend_url}/agent/confirm?token={token}"


@router.post("/human-agents", response_model=dict)
async def add_human_agents(request: HumanAgentsRequest):
    """Add human agents and send confirmation emails."""
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        async with railway_db.acquire() as conn:
            # Create email service with database connection
            email_service = create_email_service(conn)
            agents_created = []
            
            for email in request.emails:
                # Check if agent already exists
                existing = await conn.fetchrow(
                    "SELECT id, status, confirmation_token FROM human_agents WHERE email = $1",
                    email
                )
                
                if existing:
                    if existing['status'] == 'confirmed':
                        # Already confirmed, skip
                        logger.info(f"Agent {email} already confirmed, skipping")
                        continue
                    elif existing['status'] == 'pending':
                        # Resend confirmation email with existing password
                        token = existing['confirmation_token']
                        # Get existing password
                        existing_with_password = await conn.fetchrow(
                            "SELECT confirmation_token, auto_generated_password FROM human_agents WHERE email = $1",
                            email
                        )
                        password = existing_with_password.get('auto_generated_password') if existing_with_password else None
                        # If no password exists, generate one and store it
                        if not password:
                            password = generate_password()
                            await conn.execute(
                                "UPDATE human_agents SET auto_generated_password = $1 WHERE email = $2",
                                password, email
                            )
                        confirmation_link = generate_confirmation_link(token)
                        if await email_service.send_confirmation_email(email, confirmation_link, password):
                            agents_created.append({
                                "email": email,
                                "status": "pending",
                                "confirmation_token": token
                            })
                        continue
                
                # Create new agent with auto-generated password
                token = generate_confirmation_token()
                password = generate_password()
                agent_id = await conn.fetchval(
                    """
                    INSERT INTO human_agents (email, status, confirmation_token, auto_generated_password)
                    VALUES ($1, 'pending', $2, $3)
                    RETURNING id::text
                    """,
                    email, token, password
                )
                
                # Generate confirmation link
                confirmation_link = generate_confirmation_link(token)
                
                # Send confirmation email with password
                if await email_service.send_confirmation_email(email, confirmation_link, password):
                    agents_created.append({
                        "email": email,
                        "status": "pending",
                        "confirmation_token": token
                    })
                    logger.info(f"Confirmation email sent to {email}")
                else:
                    logger.warning(f"Failed to send confirmation email to {email}")
            
            return {
                "success": True,
                "message": "Confirmation emails sent to agents",
                "agents": agents_created
            }
    except Exception as e:
        logger.error(f"Error adding human agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding agents: {str(e)}")


# Human agent confirmation endpoint removed - agents are now activated immediately


@router.delete("/human-agents/{email}", response_model=dict)
async def remove_human_agent(email: str):
    """Remove human agent and send removal notification."""
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        async with railway_db.acquire() as conn:
            # Check if agent exists
            agent = await conn.fetchrow(
                "SELECT id, email, status FROM human_agents WHERE email = $1",
                email
            )
            
            if not agent:
                raise HTTPException(status_code=404, detail="Agent not found")
            
            # Update agent status
            await conn.execute(
                """
                UPDATE human_agents 
                SET status = 'removed',
                    removed_at = NOW()
                WHERE email = $1
                """,
                email
            )
            
            # Send removal email
            email_service = create_email_service(conn)
            if await email_service.send_removal_email(email):
                logger.info(f"Removal email sent to {email}")
            else:
                logger.warning(f"Failed to send removal email to {email}")
            
            return {
                "success": True,
                "message": "Agent removed successfully"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing agent: {str(e)}")

