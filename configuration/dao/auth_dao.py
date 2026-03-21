"""
Authentication Data Access Object for Configuration Service
Handles database operations for user authentication and role management
"""
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("auth_dao", "configuration")

class AuthDAO:
    def __init__(self):
        # Simple in-memory cache with TTL for rarely-changing data
        self._cache = {}
        self._cache_ttl = 60  # 60 seconds cache
    
    def _get_cached(self, key: str):
        """Get cached value if not expired"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                logger.debug(f"✅ Cache hit for {key}")
                return value
            else:
                logger.debug(f"⏰ Cache expired for {key}")
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, value: Any):
        """Set cached value with timestamp"""
        self._cache[key] = (value, time.time())
        logger.debug(f"💾 Cached {key}")

    async def check_user_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if user exists for given email."""
        query = text("""
            SELECT id, email, display_name, email_verified, created_at, updated_at
            FROM users
            WHERE email = :email
        """)
        params = {"email": email}
        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                row = result.fetchone()
                logger.log_db_query(str(query), params, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            raise  # ← Raise exception instead of returning None

    async def check_user_has_role(self, email: str, role_name: str) -> Optional[Dict[str, Any]]:
        """Check if user has specific role and return user role mapping."""
        query = text("""
            SELECT urm.user_role_id, urm.user_id, urm.role_id, urm.created_at,
                   u.email, u.display_name, r.role_name, r.role_description
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE u.email = :email AND r.role_name = :role_name
        """)
        params = {"email": email, "role_name": role_name}
        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                row = result.fetchone()
                logger.log_db_query(str(query), params, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            raise  # ← Raise exception instead of returning None

    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        return await self.check_user_has_role(email, 'admin')

    async def check_human_agent_exists(self, email: str) -> bool:
        """Check if human agent exists"""
        result = await self.check_user_has_role(email, 'human_agent')
        return result is not None

    async def get_user_roles(self, email: str) -> List[Dict[str, Any]]:
        """Get all roles for a user."""
        query = text("""
            SELECT urm.user_role_id, r.role_name, r.role_description, urm.created_at
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE u.email = :email
            AND u.is_active = true
            AND urm.is_active = true
            ORDER BY r.role_name
        """)
        params = {"email": email}
        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                results = await session.execute(query, params)
                rows = results.fetchall()
                logger.log_db_query(str(query), params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            raise  # ← Raise exception instead of returning []

    async def get_user_by_role_id(self, user_role_id: str) -> Optional[Dict[str, Any]]:
        """Get user and role information by user_role_id."""
        query = text("""
            SELECT urm.user_role_id, urm.user_id, urm.role_id, urm.created_at,
                   u.email, u.display_name, u.email_verified, u.created_at as user_created_at,
                   r.role_name, r.role_description
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE urm.user_role_id = :user_role_id
        """)
        params = {"user_role_id": user_role_id}
        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                row = result.fetchone()
                logger.log_db_query(str(query), params, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return None

    async def add_user_role(self, email: str, role_name: str) -> Optional[Dict[str, Any]]:
        """Add a role to a user. Creates user if doesn't exist."""
        # First, ensure user exists
        user = await self.check_user_exists(email)
        if not user:
            # Create new user
            create_user_query = text("""
                INSERT INTO users (email, created_at, updated_at)
                VALUES (:email, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                RETURNING id, email, created_at, updated_at
            """)
            params = {"email": email}
            try:
                logger.log_db_operation(str(create_user_query), params)
                async with get_db_session() as session:
                    result = await session.execute(create_user_query, params)
                    user_row = result.fetchone()
                    user = dict(user_row._mapping) if user_row else None
                    logger.log_db_query(str(create_user_query), params, user_row)
                    if user:
                        await session.commit()
            except Exception as e:
                logger.log_db_query(str(create_user_query), params, error=e)
                return None

        # Get role_id
        role_query = text("SELECT id FROM roles WHERE role_name = :role_name")
        params = {"role_name": role_name}
        try:
            logger.log_db_operation(str(role_query), params)
            async with get_db_session() as session:
                result = await session.execute(role_query, params)
                role_row = result.fetchone()
                logger.log_db_query(str(role_query), params, role_row)
                if not role_row:
                    logger.error(f"Role {role_name} not found")
                    return None
                role_id = role_row.id
        except Exception as e:
            logger.log_db_query(str(role_query), params, error=e)
            return None

        # Add user role mapping
        mapping_query = text("""
            INSERT INTO user_role_mapping (user_id, role_id, created_at, updated_at)
            VALUES (:user_id, :role_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (user_id, role_id) DO NOTHING
            RETURNING user_role_id, user_id, role_id, created_at, updated_at
        """)
        params = {"user_id": user['id'], "role_id": role_id}
        try:
            logger.log_db_operation(str(mapping_query), params)
            async with get_db_session() as session:
                result = await session.execute(mapping_query, params)
                mapping_row = result.fetchone()
                logger.log_db_query(str(mapping_query), params, mapping_row)
                if mapping_row:
                    await session.commit()
                return dict(mapping_row._mapping) if mapping_row else None
        except Exception as e:
            logger.log_db_query(str(mapping_query), params, error=e)
            return None

    async def remove_user_role(self, email: str, role_name: str) -> bool:
        """Remove a role from a user."""
        query = text("""
            DELETE FROM user_role_mapping
            WHERE user_id = (SELECT id FROM users WHERE email = :email)
            AND role_id = (SELECT id FROM roles WHERE role_name = :role_name)
        """)
        params = {"email": email, "role_name": role_name}
        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                logger.log_db_query(str(query), params, f"DELETE {result.rowcount}")
                await session.commit()
                return True
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return False

    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all users with admin role (cached for 60s)."""
        # Check cache first
        cached = self._get_cached('admins')
        if cached is not None:
            return cached
        
        query = text("""
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
            AND u.is_active = true
            AND urm.is_active = true
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            return []

    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all users with human_agent role."""
        query = text("""
            SELECT urm.user_role_id, u.email, u.created_at as user_created_at,
                   urm.created_at as role_assigned_at
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
            AND u.is_active = true
            AND urm.is_active = true
            ORDER BY u.email
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
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
        query = text("""
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                emails = [row.email for row in rows]
                logger.log_db_query(str(query), None, emails)
                return emails
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            return []

    async def sync_human_agent_emails(self) -> List[str]:
        """Get all human agent emails."""
        query = text("""
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
        """)
        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                emails = [row.email for row in rows]
                logger.log_db_query(str(query), None, emails)
                return emails
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            return []

    async def get_or_create_unique_id(self, email: str, role: str) -> Dict[str, Any]:
        """Get or create a unique ID for a user."""
        try:
            # Check if user exists
            user_query = text("SELECT id FROM users WHERE email = :email")
            logger.log_db_operation(str(user_query), {"email": email})

            async with get_db_session() as session:
                result = await session.execute(user_query, {"email": email})
                user_row = result.fetchone()

                # If user doesn't exist, create them
                if not user_row:
                    create_user_query = text("""
                        INSERT INTO users (email, is_active, created_at, updated_at)
                        VALUES (:email, true, NOW(), NOW())
                        RETURNING id
                    """)
                    logger.log_db_operation(str(create_user_query), {"email": email})
                    result = await session.execute(create_user_query, {"email": email})
                    user_id_row = result.fetchone()
                    user_id = user_id_row.id if user_id_row else None
                    logger.log_db_query(str(create_user_query), {"email": email}, user_id)
                    await session.commit()
                else:
                    user_id = user_row.id

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
