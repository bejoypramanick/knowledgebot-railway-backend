"""
Personas Endpoints
Handles chatbot persona management and activation.
"""
from fastapi import APIRouter, HTTPException, Depends, Request

from configuration.core.logging_config import get_railway_logger

from ..service.personas_service import PersonasService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["personas"])


@router.get("/personas", response_model=dict)
async def get_personas(request: Request):
    """Get all available chatbot personas."""
    try:
        service = PersonasService()
        result = await service.get_personas()
        return result
    except Exception as e:
        logger.error(f"Error fetching personas: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching personas: {str(e)}")


@router.post("/personas/{persona_name}/activate", response_model=dict)
async def activate_persona(
    request: Request,
    persona_name: str
):
    """Activate a specific chatbot persona."""
    try:
        # Get user email from headers (set by API Gateway)
        user_email = request.headers.get("X-User-Email", "")
        
        service = PersonasService()
        result = await service.activate_persona(persona_name, user_email)
        return result
    except Exception as e:
        logger.error(f"Error activating persona: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error activating persona: {str(e)}")
