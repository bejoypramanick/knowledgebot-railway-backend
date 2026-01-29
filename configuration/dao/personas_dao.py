"""
Personas Data Access Object
Handles database operations for chatbot personas
"""
from typing import Any, Dict, List, Optional
import asyncpg

from configuration.core.logging_config import get_railway_logger
from shared.database_initializer import get_db_connection

logger = get_railway_logger(__name__)

class PersonasDAO:
    """Data Access Object for personas operations"""
    
    async def get_all_personas(self) -> List[Dict[str, Any]]:
        """Get all personas from database"""
        try:
            conn = await get_db_connection()
            query = """
                SELECT id, persona_name, persona_description, system_prompt, 
                       is_active, created_at, updated_at, created_by_email
                FROM public.chatbot_personas
                ORDER BY persona_name
            """
            rows = await conn.fetch(query)
            await conn.close()
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise
    
    async def get_persona_by_name(self, persona_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific persona by name"""
        try:
            conn = await get_db_connection()
            query = """
                SELECT id, persona_name, persona_description, system_prompt, 
                       is_active, created_at, updated_at, created_by_email
                FROM public.chatbot_personas
                WHERE persona_name = $1
            """
            row = await conn.fetchrow(query, persona_name)
            await conn.close()
            
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching persona {persona_name}: {e}")
            raise
    
    async def activate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Activate a persona (set is_active to true)"""
        try:
            conn = await get_db_connection()
            
            # First check if persona exists
            persona = await self.get_persona_by_name(persona_name)
            if not persona:
                raise ValueError(f"Persona '{persona_name}' not found")
            
            # Update the persona to be active
            query = """
                UPDATE public.chatbot_personas 
                SET is_active = true, updated_at = NOW()
                WHERE persona_name = $1
                RETURNING id, persona_name, persona_description, system_prompt, 
                         is_active, created_at, updated_at, created_by_email
            """
            row = await conn.fetchrow(query, persona_name)
            await conn.close()
            
            return dict(row)
        except Exception as e:
            logger.error(f"Error activating persona {persona_name}: {e}")
            raise
    
    async def deactivate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Deactivate a persona (set is_active to false)"""
        try:
            conn = await get_db_connection()
            
            # First check if persona exists
            persona = await self.get_persona_by_name(persona_name)
            if not persona:
                raise ValueError(f"Persona '{persona_name}' not found")
            
            # Update the persona to be inactive
            query = """
                UPDATE public.chatbot_personas 
                SET is_active = false, updated_at = NOW()
                WHERE persona_name = $1
                RETURNING id, persona_name, persona_description, system_prompt, 
                         is_active, created_at, updated_at, created_by_email
            """
            row = await conn.fetchrow(query, persona_name)
            await conn.close()
            
            return dict(row)
        except Exception as e:
            logger.error(f"Error deactivating persona {persona_name}: {e}")
            raise
