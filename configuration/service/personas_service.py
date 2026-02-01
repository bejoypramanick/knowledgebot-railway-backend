"""
Personas Service Layer
Provides business logic for persona management operations
"""
from typing import Any, Dict, List, Optional

from configuration.core.otel_logger import get_otel_logger

from ..dao.personas_dao import PersonasDAO

logger = get_otel_logger("personas_service", "configuration")

class PersonasService:
    """Service layer for personas management"""
    
    def __init__(self):
        self.personas_dao = PersonasDAO()  # Service manages its own DAO
    
    async def get_active_persona(self) -> Dict[str, Any]:
        """Get all available personas with business logic"""
        try:
            persona = await self.personas_dao.get_active_persona()
            return persona
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise

    async def get_all_personas(self) -> Dict[str, Any]:
        """Get all available personas with business logic"""
        try:
            active_personas = await self.personas_dao.get_all_personas()
            
            return {
                "personas": active_personas,
                "total_count": len(active_personas)
            }
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise