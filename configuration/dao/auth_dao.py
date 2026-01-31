"""
Authentication Data Access Object for Configuration Service
Handles database operations for user authentication and role management
"""
from typing import Any, Dict, List, Optional

from configuration.core.db import get_db_connection
from configuration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class AuthDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        query = """
            SELECT email, status, created_at 
            FROM admins 
            WHERE email = $1 AND status = 'active'
        """
        logger.info(f"🔍 [DB QUERY] check_admin_exists: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, email)
                logger.info(f"✅ [DB RESULT] check_admin_exists: Found admin={result is not None}")
                return result
        except Exception as e:
            logger.error(f"❌ [DB ERROR] check_admin_exists: {e}")
            return None

    async def check_human_agent_exists(self, email: str) -> bool:
        """Check if human agent exists"""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval("""
                    SELECT COUNT(*) 
                    FROM human_agents 
                    WHERE email = $1 AND status = 'active'
                """, email)
                return bool(result)
        except Exception as e:
            logger.error(f"Error checking human agent exists: {e}")
            return False

    async def remove_admin(self, email: str) -> None:
        """Remove an admin by setting status to removed."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    UPDATE admins 
                    SET status = 'removed', updated_at = NOW() 
                    WHERE email = $1
                """, email)
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            raise

    async def add_admin(self, email: str) -> None:
        """Add a new admin."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO admins (email, status, created_by_email, created_at)
                    VALUES ($1, 'active', 'system', NOW())
                    ON CONFLICT (email) DO NOTHING
                """, email)
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            raise

    async def add_human_agent(self, email: str) -> bool:
        """Add a new human agent."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO human_agents (email, status, created_by_email, created_at)
                    VALUES ($1, 'active', 'system', NOW())
                    ON CONFLICT (email) DO NOTHING
                """, email)
                return True
        except Exception as e:
            logger.error(f"Error adding human agent: {e}")
            return False

    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all admins"""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch("""
                    SELECT email, status, created_at, updated_at
                    FROM admins
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                """)
        except Exception as e:
            logger.error(f"Error getting admins: {e}")
            raise

    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch("""
                    SELECT email, status, created_at, updated_at
                    FROM human_agents
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                """)
        except Exception as e:
            logger.error(f"Error getting human agents: {e}")
            raise

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get available human agents for assignment."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch("""
                    SELECT email, status, created_at
                    FROM human_agents
                    WHERE status = 'active'
                    ORDER BY created_at DESC
                """)
        except Exception as e:
            logger.error(f"Error getting available agents: {e}")
            raise

    async def remove_human_agent(self, email: str) -> None:
        """Remove a human agent by setting status to removed."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    UPDATE human_agents 
                    SET status = 'removed', updated_at = NOW() 
                    WHERE email = $1
                """, email)
        except Exception as e:
            logger.error(f"Error removing human agent: {e}")
            raise

    async def create_human_agent(self, email: str) -> str:
        """Create a new human agent."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval("""
                    INSERT INTO human_agents (email, status, created_by_email, created_at)
                    VALUES ($1, 'active', 'system', NOW())
                    RETURNING id
                """, email)
        except Exception as e:
            logger.error(f"Error creating human agent: {e}")
            raise

    async def execute_role_query(self, query: str, email: str) -> List[Dict[str, Any]]:
        """Execute role query."""
        try:
            async with get_db_connection() as conn:
                # This would need to be implemented based on actual requirements
                # For now, return empty list
                return []
        except Exception as e:
            logger.error(f"Error executing role query: {e}")
            raise
