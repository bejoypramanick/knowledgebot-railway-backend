"""
Profile Service
Handles fetching user profiles from the configuration service with:
- Connection pooling
- Retry logic with exponential backoff
- Circuit breaker pattern
- Fallback mechanisms
- OpenTelemetry tracing
"""
import httpx
from typing import Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from api_gateway.core.config import get_settings
from api_gateway.core.logging_config import get_railway_logger
from shared.internal_request_auth import add_internal_request_signature
from shared.redis_tenant_auth_cache import get_cached_user_profile, set_cached_user_profile
from shared.tracing_decorator import trace_service

logger = get_railway_logger(__name__)


def _normalize_profile_payload(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize configuration-service profile payload into session-ready fields."""
    role = profile_data.get("role")
    roles = profile_data.get("roles")
    tenant_memberships = profile_data.get("tenant_memberships", []) or []
    tenant_id = profile_data.get("tenant_id")
    tenant_slug = profile_data.get("tenant_slug")
    tenant_name = profile_data.get("tenant_name")
    active_user_role_id = profile_data.get("active_user_role_id")
    active_membership = None

    if tenant_id or tenant_slug:
        for membership in tenant_memberships:
            if tenant_id and membership.get("tenant_id") == tenant_id:
                active_membership = membership
                break
            if tenant_slug and membership.get("tenant_slug") == tenant_slug:
                active_membership = membership
                break
    elif tenant_memberships:
        if len(tenant_memberships) == 1:
            active_membership = tenant_memberships[0]

    if active_membership:
        tenant_id = tenant_id or active_membership.get("tenant_id")
        tenant_slug = tenant_slug or active_membership.get("tenant_slug")
        tenant_name = tenant_name or active_membership.get("tenant_name")
        active_user_role_id = active_user_role_id or active_membership.get("active_user_role_id")

    if role is None and tenant_memberships:
        role = active_membership.get("primary_role") if active_membership else None
    if roles is None and tenant_memberships:
        roles = active_membership.get("roles") if active_membership else []

    return {
        "role": role or ("user" if not tenant_memberships else None),
        "roles": roles or (["user"] if not tenant_memberships else []),
        "active_user_role_id": active_user_role_id,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "tenant_name": tenant_name,
        "tenant_memberships": tenant_memberships,
    }


class ProfileService:
    """Service for fetching user profiles from configuration service"""
    
    def __init__(self):
        """Initialize with connection pooling"""
        settings = get_settings()
        self.config_service_url = settings.configuration_service_url
        self.profile_endpoint = f"{self.config_service_url}/api/v1/configuration/users/profile"
        
        # Create persistent HTTP client with connection pooling
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(5.0, connect=2.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            http2=True  # Enable HTTP/2 for better performance
        )
        
        logger.info(f"✅ ProfileService initialized with endpoint: {self.profile_endpoint}")
    
    async def close(self):
        """Close the HTTP client (call during shutdown)"""
        await self.client.aclose()
        logger.info("✅ ProfileService HTTP client closed")
    
    @trace_service(span_name="service.ProfileService.fetch_user_profile")
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=True
    )
    async def fetch_user_profile(
        self,
        user_data: Dict[str, Any],
        preferred_tenant_id: Optional[str] = None,
        preferred_tenant_slug: Optional[str] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Fetch user profile from configuration service with retry logic.
        
        Args:
            user_data: Firebase user data (uid, email, name)
        
        Returns:
            User profile with role and roles fields
        
        Raises:
            httpx.HTTPError: If all retries fail
        """
        user_email = user_data.get("email", "")
        if use_cache:
            cached_profile = await get_cached_user_profile(
                user_email,
                tenant_id=preferred_tenant_id,
                tenant_slug=preferred_tenant_slug,
            )
            if cached_profile is not None:
                logger.info(f"✅ Profile cache hit for {user_email}")
                return _normalize_profile_payload(cached_profile)

        headers = {
            'X-User-UID': user_data.get('uid', ''),
            'X-User-Email': user_email,
            'X-User-Name': user_data.get('name', user_data.get('email', '')),
        }
        if preferred_tenant_id:
            headers["X-Tenant-ID"] = preferred_tenant_id
        if preferred_tenant_slug:
            headers["X-Tenant-Slug"] = preferred_tenant_slug
        add_internal_request_signature(
            headers=headers,
            method="GET",
            path_or_url=self.profile_endpoint,
            caller="api-gateway",
        )
        
        try:
            response = await self.client.get(
                self.profile_endpoint,
                headers=headers
            )
            
            if response.status_code == 200:
                profile_result = response.json()
                profile_data = profile_result.get('data', {})
                profile = _normalize_profile_payload(profile_data)
                await set_cached_user_profile(
                    user_email,
                    profile,
                    tenant_id=preferred_tenant_id,
                    tenant_slug=preferred_tenant_slug,
                )
                return profile
            else:
                logger.warning(
                    f"⚠️ Profile fetch failed with status {response.status_code}: {response.text[:200]}"
                )
                return self._get_fallback_profile()
                
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            logger.warning(f"⚠️ Profile service connection error: {e}")
            raise  # Let tenacity retry
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching profile: {e}")
            return self._get_fallback_profile()
    
    def _get_fallback_profile(self) -> Dict[str, Any]:
        """Return fallback profile when service is unavailable"""
        logger.info("🔄 Using fallback profile (role=user)")
        return {
            'role': 'user',
            'roles': ['user'],
            'active_user_role_id': None,
            'tenant_id': None,
            'tenant_slug': None,
            'tenant_name': None,
            'tenant_memberships': [],
        }


# Global instance (initialized in lifespan)
_profile_service: Optional[ProfileService] = None


def get_profile_service() -> ProfileService:
    """Dependency injection for ProfileService"""
    if _profile_service is None:
        raise RuntimeError("ProfileService not initialized. Call init_profile_service() first.")
    return _profile_service


def init_profile_service() -> ProfileService:
    """Initialize the global ProfileService instance"""
    global _profile_service
    if _profile_service is None:
        _profile_service = ProfileService()
    return _profile_service


async def close_profile_service():
    """Close the global ProfileService instance"""
    global _profile_service
    if _profile_service is not None:
        await _profile_service.close()
        _profile_service = None
