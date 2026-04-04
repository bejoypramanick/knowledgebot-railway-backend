"""
Auth Service Layer
Provides business logic for authentication operations
"""
from typing import Any, Dict, List, Optional
from fastapi import HTTPException

from shared.otel_logger import get_otel_logger
from shared.redis_tenant_auth_cache import (
    get_cached_role_directory,
    get_cached_user_memberships,
    get_cached_user_profile,
    set_cached_role_directory,
    set_cached_user_memberships,
    set_cached_user_profile,
)

from ..dao.auth_dao import AuthDAO

logger = get_otel_logger("auth_service", "configuration")


def _role_priority(role_name: str) -> int:
    if role_name == "admin":
        return 0
    if role_name == "human_agent":
        return 1
    return 2

class AuthService:
    """Service layer for authentication"""
    
    def __init__(self):
        self.auth_dao = AuthDAO()  # Service manages its own DAO
    
    
    async def get_user_role(
        self,
        email: str,
        tenant_id: Optional[str] = None,
        tenant_slug: Optional[str] = None,
    ) -> dict:
        """Get the active tenant role context for a given email."""
        try:
            cached_profile = await get_cached_user_profile(
                email,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
            )
            if cached_profile is not None:
                return cached_profile

            tenant_memberships = await get_cached_user_memberships(email)
            if tenant_memberships is None:
                memberships = await self.auth_dao.get_user_memberships(email)
                tenant_memberships = self._group_memberships(memberships)
                await set_cached_user_memberships(email, tenant_memberships)

            active_membership = self._select_active_membership(
                tenant_memberships,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
            )

            active_roles = active_membership.get("roles", []) if active_membership else []
            if not active_roles:
                active_roles = ["user"]

            primary_role = active_membership.get("primary_role") if active_membership else "user"
            active_user_role_id = active_membership.get("active_user_role_id") if active_membership else None

            active_tenant = None
            if active_membership:
                active_tenant = {
                    "tenant_id": active_membership["tenant_id"],
                    "tenant_slug": active_membership["tenant_slug"],
                    "tenant_name": active_membership["tenant_name"],
                }

            result = {
                "email": email,
                "roles": active_roles,
                "primary_role": primary_role,
                "active_user_role_id": active_user_role_id,
                "active_tenant": active_tenant,
                "tenant_memberships": tenant_memberships,
            }
            await set_cached_user_profile(
                email,
                result,
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
            )
            return result
        except Exception as e:
            exc_type = type(e).__name__
            exc_msg = str(e) if str(e) else f"({exc_type})"
            logger.error(f"Error getting user role for {email}: {exc_type}: {exc_msg}")
            raise

    def _group_memberships(self, memberships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}

        for membership in memberships:
            tenant_id = str(membership["tenant_id"])
            tenant_entry = grouped.setdefault(
                tenant_id,
                {
                    "tenant_id": tenant_id,
                    "tenant_slug": membership["tenant_slug"],
                    "tenant_name": membership["tenant_name"],
                    "roles": [],
                    "role_memberships": [],
                    "primary_role": "user",
                    "active_user_role_id": None,
                },
            )

            role_name = membership["role_name"]
            tenant_entry["roles"].append(role_name)
            tenant_entry["role_memberships"].append(
                {
                    "role": role_name,
                    "user_role_id": str(membership["user_role_id"]),
                }
            )

        memberships_by_tenant = list(grouped.values())
        for tenant_entry in memberships_by_tenant:
            tenant_entry["roles"] = sorted(set(tenant_entry["roles"]), key=_role_priority)
            tenant_entry["role_memberships"].sort(key=lambda item: _role_priority(item["role"]))
            tenant_entry["primary_role"] = tenant_entry["roles"][0] if tenant_entry["roles"] else "user"
            tenant_entry["active_user_role_id"] = (
                tenant_entry["role_memberships"][0]["user_role_id"]
                if tenant_entry["role_memberships"]
                else None
            )

        memberships_by_tenant.sort(
            key=lambda item: (
                0 if item["tenant_slug"] == "default" else 1,
                item["tenant_name"],
            )
        )
        return memberships_by_tenant

    def _select_active_membership(
        self,
        memberships: List[Dict[str, Any]],
        tenant_id: Optional[str] = None,
        tenant_slug: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not memberships:
            return None

        if tenant_id:
            for membership in memberships:
                if membership["tenant_id"] == tenant_id:
                    return membership

        if tenant_slug:
            for membership in memberships:
                if membership["tenant_slug"] == tenant_slug:
                    return membership

        if tenant_id or tenant_slug:
            logger.warning(
                "Requested tenant did not match any active membership; falling back to the first membership"
            )

        return memberships[0]

    async def remove_admin(self, email: str, current_user_email: str) -> dict:
        """Remove an admin. Only admins can remove other admins."""
        # Check if current user is an admin
        current_user_roles = await self.get_user_role(current_user_email)
        
        if 'admin' not in current_user_roles['roles']:
            raise HTTPException(status_code=403, detail="Only admins can remove other admins")
        
        # Check if user has admin role
        user_roles = await self.get_user_role(email)
        
        if 'admin' not in user_roles['roles']:
            raise HTTPException(status_code=404, detail="Admin not found")
        
        # Remove admin role
        success = await self.auth_dao.remove_user_role(email, 'admin')
        
        return {
            "success": success,
            "message": "Admin removed successfully"
        }

    async def add_admin(self, email: str) -> bool:
        """Add admin user"""
        try:
            result = await self.auth_dao.add_user_role(email, 'admin')
            return result is not None
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            raise
    
    async def add_human_agent(self, email: str) -> bool:
        """Add human agent"""
        try:
            result = await self.auth_dao.add_user_role(email, 'human_agent')
            return result is not None
        except Exception as e:
            logger.error(f"Error adding human agent: {e}")
            raise
    
    async def get_admins(self) -> List[Dict[str, Any]]:
        """Get all admins"""
        try:
            cached = await get_cached_role_directory("admin")
            if cached is not None:
                return cached

            admins = await self.auth_dao.get_admins()
            await set_cached_role_directory("admin", admins)
            return admins
        except Exception as e:
            logger.error(f"Error fetching admins: {e}")
            raise
    
    async def get_human_agents(self) -> List[Dict[str, Any]]:
        """Get all human agents"""
        try:
            cached = await get_cached_role_directory("human_agent")
            if cached is not None:
                return cached

            agents = await self.auth_dao.get_human_agents()
            await set_cached_role_directory("human_agent", agents)
            return agents
        except Exception as e:
            logger.error(f"Error fetching human agents: {e}")
            raise

    async def remove_human_agent(self, email: str, current_user_email: str) -> dict:
        """Remove a human agent"""
        # Check if current user is an admin
        current_user_roles = await self.get_user_role(current_user_email)
        
        if 'admin' not in current_user_roles['roles']:
            raise HTTPException(status_code=403, detail="Only admins can remove human agents")
        
        # Check if user has human agent role
        user_roles = await self.get_user_role(email)
        
        if 'human_agent' not in user_roles['roles']:
            raise HTTPException(status_code=404, detail="Human agent not found")
        
        # Remove human agent role
        success = await self.auth_dao.remove_user_role(email, 'human_agent')
        
        return {
            "success": success,
            "message": "Human agent removed successfully"
        }

    async def get_or_create_unique_id(self, email: str, role: str) -> dict:
        """Get or create a unique ID for a user"""
        try:
            result = await self.auth_dao.get_or_create_unique_id(email, role)
            return result
        except Exception as e:
            logger.error(f"Error in get_or_create_unique_id: {e}", exc_info=True)
            raise
