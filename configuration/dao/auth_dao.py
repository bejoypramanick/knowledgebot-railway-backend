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
        query = """
            SELECT COUNT(*) 
            FROM human_agents 
            WHERE email = $1 AND status = 'active'
        """
        logger.info(f"🔍 [DB QUERY] check_human_agent_exists: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                exists = bool(result)
                logger.info(f"✅ [DB RESULT] check_human_agent_exists: Agent exists={exists}")
                return exists
        except Exception as e:
            logger.error(f"❌ [DB ERROR] check_human_agent_exists: {e}")
            return False

    async def remove_admin(self, email: str) -> None:
        """Remove an admin by setting status to removed."""
        query = """
            UPDATE admins 
            SET status = 'removed', updated_at = NOW() 
            WHERE email = $1
        """
        logger.info(f"🔍 [DB QUERY] remove_admin: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.info(f"✅ [DB RESULT] remove_admin: Rows affected={result}")
        except Exception as e:
            logger.error(f"❌ [DB ERROR] remove_admin: {e}")
            raise

    async def add_admin(self, email: str) -> None:
        """Add a new admin."""
        query = """
            INSERT INTO admins (email, status, created_by_email, created_at)
            VALUES ($1, 'active', 'system', NOW())
            ON CONFLICT (email) DO NOTHING
        """
        logger.info(f"🔍 [DB QUERY] add_admin: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.info(f"✅ [DB RESULT] add_admin: Admin added, rows affected={result}")
        except Exception as e:
            logger.error(f"❌ [DB ERROR] add_admin: {e}")
            raise

    async def add_human_agent(self, email: str) -> bool:
        """Add a new human agent."""
        query = """
            INSERT INTO human_agents (email, status, created_by_email, created_at)
            VALUES ($1, 'active', 'system', NOW())
            ON CONFLICT (email) DO NOTHING
        """
        logger.info(f"🔍 [DB QUERY] add_human_agent: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.info(f"✅ [DB RESULT] add_human_agent: Agent added, rows affected={result}")
                return True
        except Exception as e:
            logger.error(f"❌ [DB ERROR] add_human_agent: {e}")
            return False

    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all admins"""
        query = """
            SELECT email, status, created_at, updated_at
            FROM admins
            WHERE status = 'active'
            ORDER BY created_at DESC
        """
        logger.info(f"🔍 [DB QUERY] get_admins: {query.strip()} | PARAMS: None")
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.info(f"✅ [DB RESULT] get_admins: Found {len(records)} admins")
                return records
        except Exception as e:
            logger.error(f"❌ [DB ERROR] get_admins: {e}")
            raise

    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        query = """
            SELECT email, status, created_at, updated_at
            FROM human_agents
            WHERE status = 'active'
            ORDER BY created_at DESC
        """
        logger.info(f"🔍 [DB QUERY] get_human_agents: {query.strip()} | PARAMS: None")
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.info(f"✅ [DB RESULT] get_human_agents: Found {len(records)} agents")
                return records
        except Exception as e:
            logger.error(f"❌ [DB ERROR] get_human_agents: {e}")
            raise

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get available human agents for assignment."""
        query = """
            SELECT email, status, created_at
            FROM human_agents
            WHERE status = 'active'
            ORDER BY created_at DESC
        """
        logger.info(f"🔍 [DB QUERY] get_available_agents: {query.strip()} | PARAMS: None")
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.info(f"✅ [DB RESULT] get_available_agents: Found {len(records)} available agents")
                return records
        except Exception as e:
            logger.error(f"❌ [DB ERROR] get_available_agents: {e}")
            raise

    async def remove_human_agent(self, email: str) -> None:
        """Remove a human agent by setting status to removed."""
        query = """
            UPDATE human_agents 
            SET status = 'removed', updated_at = NOW() 
            WHERE email = $1
        """
        logger.info(f"🔍 [DB QUERY] remove_human_agent: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.info(f"✅ [DB RESULT] remove_human_agent: Rows affected={result}")
        except Exception as e:
            logger.error(f"❌ [DB ERROR] remove_human_agent: {e}")
            raise

    async def create_human_agent(self, email: str) -> str:
        """Create a new human agent."""
        query = """
            INSERT INTO human_agents (email, status, created_by_email, created_at)
            VALUES ($1, 'active', 'system', NOW())
            RETURNING id
        """
        logger.info(f"🔍 [DB QUERY] create_human_agent: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                logger.info(f"✅ [DB RESULT] create_human_agent: Agent created with id={result}")
                return result
        except Exception as e:
            logger.error(f"❌ [DB ERROR] create_human_agent: {e}")
            raise

    async def execute_role_query(self, query: str, email: str) -> List[Dict[str, Any]]:
        """Execute role query."""
        logger.info(f"🔍 [DB QUERY] execute_role_query: {query.strip()} | PARAMS: email={email}")
        
        try:
            async with get_db_connection() as conn:
                # This would need to be implemented based on actual requirements
                # For now, return empty list
                logger.info(f"✅ [DB RESULT] execute_role_query: Query executed, no results")
                return []
        except Exception as e:
            logger.error(f"❌ [DB ERROR] execute_role_query: {e}")
            raise
