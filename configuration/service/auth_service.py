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
    invalidate_user_auth_cache,
    invalidate_role_directory,
)

from ..dao.auth_dao import AuthDAO

logger = get_otel_logger("auth_service", "configuration")


def _role_priority(role_name: str) -> int:
    if role_name == "admin":
        return 0
    if role_name == "human_agent":
        return 1
    return 2


def _normalize_role_context(
    email: str,
    tenant_memberships: List[Dict[str, Any]],
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> Dict[str, Any]:
    active_membership = None

    if tenant_id:
        for membership in tenant_memberships:
            if membership["tenant_id"] == tenant_id:
                active_membership = membership
                break

    if active_membership is None and tenant_slug:
        for membership in tenant_memberships:
            if membership["tenant_slug"] == tenant_slug:
                active_membership = membership
                break

    if active_membership is None and tenant_memberships:
        # Fall back to the first membership in the list.
        # Because _group_memberships now sorts non-default tenants first by join
        # date, this will be the earliest real tenant the admin was added to.
        active_membership = tenant_memberships[0]

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

    return {
        "email": email,
        "roles": active_roles,
        "primary_role": primary_role,
        "active_user_role_id": active_user_role_id,
        "active_tenant": active_tenant,
        "tenant_memberships": tenant_memberships,
    }

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
        from shared.tenant_context import tenant_context
        
        try:
            with tenant_context(user_email=email, tenant_id=tenant_id, tenant_slug=tenant_slug):
                cached_profile = await get_cached_user_profile(
                    email,
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                )
                if cached_profile is not None:
                    result = _normalize_role_context(
                        email,
                        cached_profile.get("tenant_memberships", []),
                        tenant_id=tenant_id
                        or (cached_profile.get("active_tenant") or {}).get("tenant_id"),
                        tenant_slug=tenant_slug
                        or (cached_profile.get("active_tenant") or {}).get("tenant_slug"),
                    )
                    # Even if cached, check if they need onboarding (memberships empty)
                    if not cached_profile.get("tenant_memberships"):
                        result["needs_onboarding"] = True
                    return result

                # 1. Primary Authorization Gate: Check if user exists in the core users table
                # If they don't exist here, they are not a pre-provisioned user and are unauthorized
                user_exists = await self.auth_dao.check_user_exists(email)
                if not user_exists:
                    logger.warning(f"🚫 Unauthorized request from {email} - and not found in users table")
                    # We raise a ValueError which the router can catch and turn into a 403
                    raise ValueError(f"User {email} is not authorized to access this system")

                # 2. Check memberships (real-time or cache)
                tenant_memberships = await get_cached_user_memberships(email)
                if tenant_memberships is None:
                    memberships = await self.auth_dao.get_user_memberships(email)
                    
                    # 3. Handle Manual Onboarding
                    # User exists in DB (checked above) but has 0 memberships
                    if not memberships:
                        logger.info(f"📋 User {email} requires manual onboarding (exists in users table but has no memberships)")
                        result = _normalize_role_context(email, [], tenant_id=tenant_id, tenant_slug=tenant_slug)
                        result["needs_onboarding"] = True
                        return result
                    
                    tenant_memberships = self._group_memberships(memberships)
                    await set_cached_user_memberships(email, tenant_memberships)

                result = _normalize_role_context(
                    email,
                    tenant_memberships,
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                )
                
                # Check for onboarding even if cache existed but was empty
                if not tenant_memberships:
                    result["needs_onboarding"] = True

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

    async def provision_tenant(self, email: str, tenant_name: str, tenant_slug: str) -> dict:
        """Process manual tenant provisioning requested by the user from UI."""
        from shared.tenant_context import tenant_context
        
        logger.info(f"🚀 Manual provisioning started for {email}: {tenant_name} ({tenant_slug})")
        
        # 1. Perform provisioning
        provision_result = await self.auth_dao.manual_provision_tenant(email, tenant_name, tenant_slug)
        
        # 2. Invalidate caches
        await invalidate_user_auth_cache(email)
        
        # 3. Return fresh role context
        return await self.get_user_role(
            email, 
            tenant_id=provision_result["tenant_id"],
            tenant_slug=provision_result["tenant_slug"]
        )

    def _group_memberships(self, memberships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}

        for membership in memberships:
            tenant_id = str(membership["tenant_id"])
            # created_at from urm is a datetime; convert to ISO string for sorting
            row_created_at = membership.get("created_at")
            row_created_at_str = (
                row_created_at.isoformat() if hasattr(row_created_at, "isoformat") else str(row_created_at or "")
            )

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
                    # Tracks the earliest urm.created_at across all role rows for
                    # this tenant — used as the login-time sort key.
                    "earliest_joined_at": row_created_at_str,
                },
            )

            # Keep the minimum (earliest) created_at across multiple role rows
            if row_created_at_str < tenant_entry["earliest_joined_at"]:
                tenant_entry["earliest_joined_at"] = row_created_at_str

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

        # Sort order:
        #   1. Non-default (real) tenants come first
        #   2. Within real tenants: earliest urm.created_at (first tenant joined)
        #   3. The "default" system tenant is always last — it should never
        #      become the active context for a real multi-tenant admin.
        memberships_by_tenant.sort(
            key=lambda item: (
                1 if item["tenant_slug"] == "default" else 0,
                item.get("earliest_joined_at") or "",
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

    async def provision_tenant(self, email: str, tenant_name: str, tenant_slug: str) -> Dict[str, Any]:
        """
        Manually provision a new tenant for a pre-provisioned user.
        Includes database operations and cache invalidation.
        """
        try:
            # 1. Perform database provisioning
            result = await self.auth_dao.manual_provision_tenant(email, tenant_name, tenant_slug)
            
            # 2. Invalidate ALL authentication caches for this user
            # This is critical so the next /profile call sees the new memberships
            from shared.redis_tenant_auth_cache import invalidate_user_auth_cache
            await invalidate_user_auth_cache(email)
            
            # 3. Return fresh profile (using common logic)
            return await self.get_user_role(email, tenant_slug=tenant_slug)
        except Exception as e:
            logger.error(f"Error in manual tenant provisioning for {email}: {e}")
            raise
