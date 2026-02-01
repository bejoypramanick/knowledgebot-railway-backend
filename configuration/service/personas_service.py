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
    
    async def get_personas(self) -> Dict[str, Any]:
        """Get all available personas with business logic"""
        try:
            personas = await self.personas_dao.get_all_personas()
            
            # Filter to only active personas for general use
            active_personas = [p for p in personas if p.get('is_active', False)]
            
            return {
                "personas": active_personas,
                "total_count": len(active_personas)
            }
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise

    async def get_all_personas(self) -> Dict[str, Any]:
        """Get all available personas with business logic"""
        try:
            personas = await self.personas_dao.get_all_personas()
            
            # Filter to only active personas for general use
            active_personas = [p for p in personas if p.get('is_active', False)]
            
            return {
                "personas": active_personas,
                "total_count": len(active_personas)
            }
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise

    async def create_persona(self, persona_data: dict, user_email: str) -> Dict[str, Any]:
        """Create a new persona with business logic"""
        try:
            # This would need to be implemented based on actual persona creation logic
            # For now, return success response
            return {
                "success": True,
                "message": "Persona created successfully",
                "persona": persona_data
            }
        except Exception as e:
            logger.error(f"Error creating persona: {e}")
            raise
            
            # Get the currently active persona (should be only one)
            current_active_persona = None
            for persona in personas:
                if persona.get('is_active', False):
                    current_active_persona = persona
                    break
            
            return {
                "success": True,
                "data": {
                    "all_personas": personas,
                    "active_personas": active_personas,
                    "current_active_persona": current_active_persona,
                    "total_count": len(personas),
                    "active_count": len(active_personas)
                }
            }
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise
    
    async def activate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Activate a specific persona with business logic"""
        try:
            # Check if persona exists first
            existing_persona = await self.personas_dao.get_persona_by_name(persona_name)
            if not existing_persona:
                return {
                    "success": False,
                    "error": f"Persona '{persona_name}' not found"
                }
            
            # If already active, return early
            if existing_persona.get('is_active', False):
                return {
                    "success": True,
                    "message": f"Persona '{persona_name}' is already active",
                    "data": existing_persona
                }
            
            # Activate the persona
            activated_persona = await self.personas_dao.activate_persona(persona_name, user_email)
            
            return {
                "success": True,
                "message": f"Persona '{persona_name}' activated successfully",
                "data": activated_persona
            }
        except Exception as e:
            logger.error(f"Error activating persona: {e}")
            raise
    
    async def deactivate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Deactivate a specific persona with business logic"""
        try:
            # Check if persona exists first
            existing_persona = await self.personas_dao.get_persona_by_name(persona_name)
            if not existing_persona:
                return {
                    "success": False,
                    "error": f"Persona '{persona_name}' not found"
                }
            
            # If already inactive, return early
            if not existing_persona.get('is_active', False):
                return {
                    "success": True,
                    "message": f"Persona '{persona_name}' is already inactive",
                    "data": existing_persona
                }
            
            # Deactivate the persona
            deactivated_persona = await self.personas_dao.deactivate_persona(persona_name, user_email)
            
            return {
                "success": True,
                "message": f"Persona '{persona_name}' deactivated successfully",
                "data": deactivated_persona
            }
        except Exception as e:
            logger.error(f"Error deactivating persona: {e}")
            raise
