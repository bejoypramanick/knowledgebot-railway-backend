"""
Authentication Data Access Object for Configuration Service
Handles database operations for user authentication and role management
"""
from typing import Any, Dict, List, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("auth_dao", "configuration")

class AuthDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def check_user_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if user exists for given email."""
        query = """
            SELECT id, email, display_name, email_verified, created_at, updated_at
            FROM users 
            WHERE email = $1
        """
        params = {"email": email}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, email)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def check_user_has_role(self, email: str, role_name: str) -> Optional[Dict[str, Any]]:
        """Check if user has specific role and return user role mapping."""
        query = """
            SELECT urm.user_role_id, urm.user_id, urm.role_id, urm.created_at,
                   u.email, u.display_name, r.role_name, r.role_description
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE u.email = $1 AND r.role_name = $2
        """
        params = {"email": email, "role_name": role_name}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, email, role_name)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        return await self.check_user_has_role(email, 'admin')

    async def check_human_agent_exists(self, email: str) -> bool:
        """Check if human agent exists"""
        result = await self.check_user_has_role(email, 'human_agent')
        return result is not None

    async def get_user_roles(self, email: str) -> List[Dict[str, Any]]:
        """Get all roles for a user."""
        query = """
            SELECT urm.user_role_id, r.role_name, r.role_description, urm.created_at
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE u.email = $1 
            AND u.is_active = true 
            AND urm.is_active = true
            ORDER BY r.role_name
        """
        params = {"email": email}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                results = await conn.fetch(query, email)
                logger.log_db_query(query, params, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def get_user_by_role_id(self, user_role_id: int) -> Optional[Dict[str, Any]]:
        """Get user and role information by user_role_id."""
        query = """
            SELECT urm.user_role_id, urm.user_id, urm.role_id, urm.created_at,
                   u.email, u.display_name, u.email_verified, u.created_at as user_created_at,
                   r.role_name, r.role_description
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE urm.user_role_id = $1
        """
        params = {"user_role_id": user_role_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, user_role_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def add_user_role(self, email: str, role_name: str) -> Optional[Dict[str, Any]]:
        """Add a role to a user. Creates user if doesn't exist."""
        # First, ensure user exists
        user = await self.check_user_exists(email)
        if not user:
            # Create new user
            create_user_query = """
                INSERT INTO users (email, created_at, updated_at)
                VALUES ($1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id, email, created_at, updated_at
            """
            params = {"email": email}
            try:
                logger.log_db_operation(create_user_query, params)
                async with get_db_connection() as conn:
                    user = await conn.fetchrow(create_user_query, email)
                    logger.log_db_query(create_user_query, params, user)
            except Exception as e:
                logger.log_db_query(create_user_query, params, error=e)
                return None

        # Get role_id
        role_query = "SELECT id FROM roles WHERE role_name = $1"
        params = {"role_name": role_name}
        try:
            logger.log_db_operation(role_query, params)
            async with get_db_connection() as conn:
                role = await conn.fetchrow(role_query, role_name)
                logger.log_db_query(role_query, params, role)
                if not role:
                    logger.error(f"Role {role_name} not found")
                    return None
                role_id = role['id']
        except Exception as e:
            logger.log_db_query(role_query, params, error=e)
            return None

        # Add user role mapping
        mapping_query = """
            INSERT INTO user_role_mapping (user_id, role_id, created_at, updated_at)
            VALUES ($1, $2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, role_id) DO NOTHING
            RETURNING user_role_id, user_id, role_id, created_at, updated_at
        """
        params = {"user_id": user['id'], "role_id": role_id}
        try:
            logger.log_db_operation(mapping_query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(mapping_query, user['id'], role_id)
                logger.log_db_query(mapping_query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(mapping_query, params, error=e)
            return None

    async def remove_user_role(self, email: str, role_name: str) -> bool:
        """Remove a role from a user."""
        query = """
            DELETE FROM user_role_mapping
            WHERE user_id = (SELECT id FROM users WHERE email = $1)
            AND role_id = (SELECT id FROM roles WHERE role_name = $2)
        """
        params = {"email": email, "role_name": role_name}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, email, role_name)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all users with admin role."""
        query = """
            SELECT urm.user_role_id, u.email, u.created_at as user_created_at,
                   urm.created_at as role_assigned_at
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin' 
            AND u.is_active = true 
            AND urm.is_active = true
            ORDER BY u.email
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                logger.log_db_query(query, None, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all users with human_agent role."""
        query = """
            SELECT urm.user_role_id, u.email, u.created_at as user_created_at,
                   urm.created_at as role_assigned_at
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
            AND u.is_active = true 
            AND urm.is_active = true
            ORDER BY u.email
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                logger.log_db_query(query, None, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get all available human agents."""
        # For now, all human agents are considered available
        return await self.get_human_agents()

    async def remove_admin(self, email: str) -> bool:
        """Remove admin role from user."""
        return await self.remove_user_role(email, 'admin')

    async def remove_human_agent(self, email: str) -> bool:
        """Remove human agent role from user."""
        return await self.remove_user_role(email, 'human_agent')

    async def add_admin(self, email: str) -> Optional[Dict[str, Any]]:
        """Add admin role to user."""
        return await self.add_user_role(email, 'admin')

    async def add_human_agent(self, email: str) -> Optional[Dict[str, Any]]:
        """Add human agent role to user."""
        return await self.add_user_role(email, 'human_agent')

    async def sync_admin_emails(self) -> List[str]:
        """Get all admin emails."""
        query = """
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                emails = [row['email'] for row in results]
                logger.log_db_query(query, None, emails)
                return emails
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def sync_human_agent_emails(self) -> List[str]:
        """Get all human agent emails."""
        query = """
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                emails = [row['email'] for row in results]
                logger.log_db_query(query, None, emails)
                return emails
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_or_create_unique_id(self, email: str, role: str) -> Dict[str, Any]:
        """Get or create a unique ID for a user."""
        try:
            # Check if user exists
            user_query = "SELECT id FROM users WHERE email = $1"
            logger.log_db_operation(user_query, {"email": email})

            async with get_db_connection() as conn:
                user = await conn.fetchrow(user_query, email)

                # If user doesn't exist, create them
                if not user:
                    create_user_query = """
                        INSERT INTO users (email, is_active, created_at, updated_at)
                        VALUES ($1, true, NOW(), NOW())
                        RETURNING id
                    """
                    logger.log_db_operation(create_user_query, {"email": email})
                    user_id = await conn.fetchval(create_user_query, email)
                    logger.log_db_query(create_user_query, {"email": email}, user_id)
                else:
                    user_id = user['id']

                # Generate unique_id based on user_id and role
                unique_id = f"{role}_{user_id}"

                return {
                    "unique_id": unique_id,
                    "user_id": user_id,
                    "email": email,
                    "role": role
                }
        except Exception as e:
            logger.error(f"Error in get_or_create_unique_id: {e}", exc_info=True)
            raise
