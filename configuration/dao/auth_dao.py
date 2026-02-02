"""
Authentication Data Access Object for Configuration Service
Handles database operations for user authentication and role management
"""
from typing import Any, Dict, List, Optional

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("auth_dao", "configuration")

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
        
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, email)
                logger.log_db_query(query, {"email": email}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            return None

    async def check_human_agent_exists(self, email: str) -> bool:
        """Check if human agent exists"""
        query = """
            SELECT COUNT(*) 
            FROM human_agents 
            WHERE email = $1 AND status = 'active'
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                exists = bool(result)
                logger.log_db_query(query, {"email": email}, result)
                return exists
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            return False

    async def remove_admin(self, email: str) -> None:
        """Remove an admin by setting status to removed."""
        query = """
            UPDATE admins 
            SET status = 'removed', updated_at = NOW() 
            WHERE email = $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.log_db_query(query, {"email": email}, result)
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            raise

    async def add_admin(self, email: str) -> None:
        """Add a new admin."""
        query = """
            INSERT INTO admins (email, status, created_by_email, created_at)
            VALUES ($1, 'active', 'system', NOW())
            ON CONFLICT (email) DO NOTHING
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.log_db_query(query, {"email": email}, result)
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            raise

    async def add_human_agent(self, email: str) -> bool:
        """Add a new human agent."""
        query = """
            INSERT INTO human_agents (email, status, created_by_email, created_at)
            VALUES ($1, 'active', 'system', NOW())
            ON CONFLICT (email) DO NOTHING
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.log_db_query(query, {"email": email}, result)
                return True
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            return False

    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all admins"""
        query = """
            SELECT email, status, created_at, updated_at
            FROM admins
            WHERE status = 'active'
            ORDER BY created_at DESC
        """
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return records
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        query = """
            SELECT email, status, created_at, updated_at
            FROM human_agents
            WHERE status = 'active'
            ORDER BY created_at DESC
        """
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return records
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get available human agents for assignment."""
        query = """
            SELECT email, status, created_at
            FROM human_agents
            WHERE status = 'active'
            ORDER BY created_at DESC
        """
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return records
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def remove_human_agent(self, email: str) -> None:
        """Remove a human agent by setting status to removed."""
        query = """
            UPDATE human_agents 
            SET status = 'removed', updated_at = NOW() 
            WHERE email = $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, email)
                logger.log_db_query(query, {"email": email}, result)
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            raise

    async def create_human_agent(self, email: str) -> str:
        """Create a new human agent."""
        query = """
            INSERT INTO human_agents (email, status, created_by_email, created_at)
            VALUES ($1, 'active', 'system', NOW())
            RETURNING id
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                logger.log_db_query(query, {"email": email}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            raise

    async def execute_role_query(self, query: str, email: str) -> List[Dict[str, Any]]:
        """Execute role query."""
        try:
            async with get_db_connection() as conn:
                # This would need to be implemented based on actual requirements
                # For now, return empty list
                logger.log_db_query(query, {"email": email}, [])
                return []
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            raise

    async def get_or_create_unique_id(self, email: str, role: str = "customer") -> Dict[str, Any]:
        """Get or create a unique ID for a user by email and role."""
        import uuid

        select_query = """
            SELECT unique_id, email, role, created_at
            FROM user_unique_ids
            WHERE email = $1 AND role = $2
        """
        params = {"email": email, "role": role}

        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(select_query, email, role)
                logger.log_db_query(select_query, params, result)

                if result:
                    return {
                        "unique_id": result["unique_id"],
                        "email": result["email"],
                        "role": result["role"]
                    }
                else:
                    # If no existing unique ID, generate one and store it
                    new_unique_id = str(uuid.uuid4())[:8]  # Short unique ID

                    insert_query = """
                        INSERT INTO user_unique_ids (email, unique_id, role)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (email, role) DO NOTHING
                    """
                    insert_result = await conn.execute(insert_query, email, new_unique_id, role)
                    logger.log_db_query(insert_query, {"email": email, "unique_id": new_unique_id, "role": role}, insert_result)

                    return {
                        "unique_id": new_unique_id,
                        "email": email,
                        "role": role,
                        "created": True
                    }
        except Exception as e:
            logger.log_db_query("get_or_create_unique_id", params, error=e)
            raise
