"""
Personas Data Access Object
Handles database operations for chatbot personas
"""
from typing import Any, Dict, List, Optional
import asyncpg

from configuration.core.logging_config import get_railway_logger
from configuration.core.db import get_db_connection

logger = get_railway_logger(__name__)

class PersonasDAO:
    """Data Access Object for personas operations"""
    
    async def get_all_personas(self) -> List[Dict[str, Any]]:
        """Get all personas from database"""
        try:
            async with get_db_connection() as conn:
                query = """
                    SELECT id, persona_name, persona_description, system_prompt, 
                           is_active, created_at, updated_at, created_by_email
                    FROM public.chatbot_personas
                    ORDER BY persona_name
                """
                rows = await conn.fetch(query)
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise
    
    async def get_persona_by_name(self, persona_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific persona by name"""
        try:
            async with get_db_connection() as conn:
                query = """
                    SELECT id, persona_name, persona_description, system_prompt, 
                           is_active, created_at, updated_at, created_by_email
                    FROM public.chatbot_personas
                    WHERE persona_name = $1
                """
                row = await conn.fetchrow(query, persona_name)
            
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error fetching persona {persona_name}: {e}")
            raise
    
    async def activate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Activate a persona (set is_active to true)"""
        try:
            async with get_db_connection() as conn:
                # First check if persona exists
                query = """
                    SELECT id, persona_name, persona_description, system_prompt, 
                           is_active, created_at, updated_at, created_by_email
                    FROM public.chatbot_personas
                    WHERE persona_name = $1
                """
                row = await conn.fetchrow(query, persona_name)
                
                if not row:
                    raise ValueError(f"Persona '{persona_name}' not found")
                
                # Update the persona to be active
                update_query = """
                    UPDATE public.chatbot_personas 
                    SET is_active = true, updated_at = NOW()
                    WHERE persona_name = $1
                    RETURNING id, persona_name, persona_description, system_prompt, 
                             is_active, created_at, updated_at, created_by_email
                """
                updated_row = await conn.fetchrow(update_query, persona_name)
            
            return dict(updated_row)
        except Exception as e:
            logger.error(f"Error activating persona {persona_name}: {e}")
            raise
    
    async def deactivate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Deactivate a persona (set is_active to false)"""
        try:
            async with get_db_connection() as conn:
                # First check if persona exists
                query = """
                    SELECT id, persona_name, persona_description, system_prompt, 
                           is_active, created_at, updated_at, created_by_email
                    FROM public.chatbot_personas
                    WHERE persona_name = $1
                """
                row = await conn.fetchrow(query, persona_name)
                
                if not row:
                    raise ValueError(f"Persona '{persona_name}' not found")
                
                # Update the persona to be inactive
                update_query = """
                    UPDATE public.chatbot_personas 
                    SET is_active = false, updated_at = NOW()
                    WHERE persona_name = $1
                    RETURNING id, persona_name, persona_description, system_prompt, 
                             is_active, created_at, updated_at, created_by_email
                """
                updated_row = await conn.fetchrow(update_query, persona_name)
            
            return dict(updated_row)
        except Exception as e:
            logger.error(f"Error deactivating persona {persona_name}: {e}")
            raise
