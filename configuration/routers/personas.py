"""
Personas Endpoints
Handles chatbot persona management and activation.
"""
from fastapi import APIRouter, HTTPException, Depends

from configuration.core.logging_config import get_railway_logger

# Placeholder for authentication since it's handled at API Gateway level
def get_current_user():
    """Placeholder function - authentication is handled at API Gateway level"""
    return {"email": "system@example.com"}

from ..service.personas_service import PersonasService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["personas"])


@router.get("/personas", response_model=dict)
async def get_personas(current_user: dict = Depends(get_current_user)):
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
    persona_name: str,
    current_user: dict = Depends(get_current_user)
):
    """Activate a specific chatbot persona."""
    try:
        service = PersonasService()
        result = await service.activate_persona(persona_name, current_user.get('email'))
        return result
    except Exception as e:
        logger.error(f"Error activating persona: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error activating persona: {str(e)}")
