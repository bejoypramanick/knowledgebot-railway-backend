"""
Personas Data Access Object for Configuration Service
Handles database operations for chatbot personas
"""
from typing import Dict, List, Any, Optional
import asyncpg

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("personas_dao", "configuration")

class PersonasDAO:
    """Data Access Object for personas operations"""
    
    async def get_all_personas(self) -> List[Dict[str, Any]]:
        """Get all personas from database"""
        try:
            async with get_db_connection() as conn:
                query = """
                    SELECT id, persona_name, system_prompt, 
                           is_active, created_at, updated_at
                    FROM public.persona_configurations
                    ORDER BY created_at DESC
                """
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
            
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching personas: {e}")
            raise

    async def get_active_persona(self) -> Optional[Dict[str, Any]]:
        """Get active chatbot persona from database."""
        query = """
            SELECT id, persona_name, persona_description, system_prompt, 
                   is_active, created_at, updated_at
            FROM persona_configurations
            WHERE is_active = true
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None
    
    async def get_persona_by_name(self, persona_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific persona by name"""
        query = """
            SELECT id, persona_name, system_prompt, 
                   is_active, created_at, updated_at
            FROM public.persona_configurations
            WHERE persona_name = $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, persona_name)
                logger.log_db_query(query, {"persona_name": persona_name}, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, {"persona_name": persona_name}, error=e)
            raise
    
    async def activate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Activate a persona (set is_active to true)"""
        query = """
            UPDATE public.persona_configurations 
            SET is_active = true, updated_at = NOW()
            WHERE persona_name = $1
            RETURNING id, persona_name, system_prompt, 
                     is_active, created_at, updated_at
        """
        try:
            async with get_db_connection() as conn:
                # First check if persona exists
                check_query = """
                    SELECT id, persona_name, system_prompt, 
                           is_active, created_at, updated_at
                    FROM public.persona_configurations
                    WHERE persona_name = $1
                """
                row = await conn.fetchrow(check_query, persona_name)
                logger.log_db_query(check_query, {"persona_name": persona_name}, row)
                
                if not row:
                    raise ValueError(f"Persona '{persona_name}' not found")
                
                # Update the persona to be active
                updated_row = await conn.fetchrow(query, persona_name)
                logger.log_db_query(query, {"persona_name": persona_name}, updated_row)
            
            return dict(updated_row)
        except Exception as e:
            logger.log_db_query(query, {"persona_name": persona_name}, error=e)
            raise
    
    async def deactivate_persona(self, persona_name: str, user_email: str) -> Dict[str, Any]:
        """Deactivate a persona (set is_active to false)"""
        query = """
            UPDATE public.persona_configurations 
            SET is_active = false, updated_at = NOW()
            WHERE persona_name = $1
            RETURNING id, persona_name, system_prompt, 
                     is_active, created_at, updated_at
        """
        try:
            async with get_db_connection() as conn:
                # First check if persona exists
                check_query = """
                    SELECT id, persona_name, system_prompt, 
                           is_active, created_at, updated_at
                    FROM public.persona_configurations
                    WHERE persona_name = $1
                """
                row = await conn.fetchrow(check_query, persona_name)
                logger.log_db_query(check_query, {"persona_name": persona_name}, row)
                
                if not row:
                    raise ValueError(f"Persona '{persona_name}' not found")
                
                # Update the persona to be inactive
                updated_row = await conn.fetchrow(query, persona_name)
                logger.log_db_query(query, {"persona_name": persona_name}, updated_row)
            
            return dict(updated_row)
        except Exception as e:
            logger.log_db_query(query, {"persona_name": persona_name}, error=e)
            raise
