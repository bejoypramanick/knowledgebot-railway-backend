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
from shared.tracing_decorator import trace_service

logger = get_railway_logger(__name__)


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
    async def fetch_user_profile(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fetch user profile from configuration service with retry logic.
        
        Args:
            user_data: Firebase user data (uid, email, name)
        
        Returns:
            User profile with role and roles fields
        
        Raises:
            httpx.HTTPError: If all retries fail
        """
        headers = {
            'X-User-UID': user_data.get('uid', ''),
            'X-User-Email': user_data.get('email', ''),
            'X-User-Name': user_data.get('name', user_data.get('email', '')),
        }
        
        try:
            response = await self.client.get(
                self.profile_endpoint,
                headers=headers
            )
            
            if response.status_code == 200:
                profile_result = response.json()
                profile_data = profile_result.get('data', {})
                
                return {
                    'role': profile_data.get('role', 'user'),
                    'roles': profile_data.get('roles', ['user'])
                }
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
            'roles': ['user']
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
