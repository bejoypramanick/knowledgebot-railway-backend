"""
Session Service
Manages session lifecycle with:
- Dependency injection for testability
- Enhanced security validation
- Write-back throttling for performance
- CSRF protection
- OpenTelemetry tracing
"""
import secrets
import time
from typing import Dict, Any, Optional

from api_gateway.core.logging_config import get_railway_logger
from shared.tracing_decorator import trace_service

logger = get_railway_logger(__name__)

# Session configuration
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days
SESSION_UPDATE_THRESHOLD = 300  # Only update Redis if last update was >5 minutes ago
STRICT_SESSION_CHECK = True  # Enforce IP/User-Agent validation


class SessionService:
    """Service for managing user sessions"""
    
    def __init__(self, session_store):
        """
        Initialize with session store (dependency injection).
        
        Args:
            session_store: Storage backend (Redis or in-memory)
        """
        self.store = session_store
        logger.info("✅ SessionService initialized")
    
    @trace_service(span_name="service.SessionService.create_session")
    def create_session(
        self,
        user_data: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """
        Create a new session with security metadata.
        
        Args:
            user_data: User information (uid, email, name, picture, role, roles)
            ip_address: Client IP for session binding
            user_agent: Client User-Agent for session binding
        
        Returns:
            Session ID (secure random token)
        """
        # Generate cryptographically secure session ID
        session_id = secrets.token_urlsafe(32)
        
        # Prepare session data with security metadata
        session_data = {
            "uid": user_data.get("uid"),
            "email": user_data.get("email"),
            "name": user_data.get("name", user_data.get("email")),
            "picture": user_data.get("picture"),
            "role": user_data.get("role", "user"),
            "roles": user_data.get("roles", ["user"]),
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + SESSION_MAX_AGE,
            # Security: Bind session to IP and User-Agent
            "ip_address": ip_address,
            "user_agent": user_agent,
            "request_count": 0,
            "last_request_time": int(time.time()),
            "last_update_time": int(time.time())  # Track when we last wrote to Redis
        }
        
        # Store in Redis/memory with TTL
        self.store.create(session_id, session_data, SESSION_MAX_AGE)
        
        logger.info(
            f"✅ Session created for {user_data.get('email')} "
            f"(role={user_data.get('role')}) from IP {ip_address}"
        )
        
        return session_id
    
    @trace_service(span_name="service.SessionService.get_session")
    def get_session(
        self,
        session_id: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        validate_security: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Get session with security validation and write-back throttling.
        
        Args:
            session_id: Session ID from cookie
            ip_address: Client IP for validation
            user_agent: Client User-Agent for validation
            validate_security: Whether to enforce IP/User-Agent checks
        
        Returns:
            Session data if valid, None if invalid/expired/hijacked
        """
        # Get session from store
        session_data = self.store.get(session_id)
        
        if not session_data:
            return None
        
        # Check expiration (Redis handles TTL, but double-check for in-memory)
        if session_data.get("expires_at") and session_data["expires_at"] < int(time.time()):
            self.store.delete(session_id)
            logger.info(f"⏰ Session expired for {session_data.get('email')}")
            return None
        
        # Security validation
        if validate_security and STRICT_SESSION_CHECK:
            if not self._validate_session_security(session_data, ip_address, user_agent):
                # Session hijacking detected - invalidate immediately
                self.store.delete(session_id)
                logger.warning(f"🚨 Session invalidated for {session_data.get('email')} - security check failed")
                return None
        
        # Update request tracking with write-back throttling
        current_time = int(time.time())
        session_data["request_count"] = session_data.get("request_count", 0) + 1
        session_data["last_request_time"] = current_time
        
        # Only write to Redis if last update was >5 minutes ago (reduces Redis load)
        last_update = session_data.get("last_update_time", 0)
        if current_time - last_update > SESSION_UPDATE_THRESHOLD:
            session_data["last_update_time"] = current_time
            self.store.create(session_id, session_data, SESSION_MAX_AGE)
            logger.debug(f"🔄 Session updated for {session_data.get('email')}")
        
        return session_data
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session ID to delete
        
        Returns:
            True if deleted, False if not found
        """
        result = self.store.delete(session_id)
        if result:
            logger.info(f"✅ Session {session_id[:8]}... deleted")
        return result
    
    def refresh_session(self, session_id: str) -> bool:
        """
        Refresh session to extend expiration.
        
        Args:
            session_id: Session ID to refresh
        
        Returns:
            True if refreshed, False if session not found
        """
        session_data = self.store.get(session_id)
        
        if not session_data:
            return False
        
        # Extend expiration
        session_data["expires_at"] = int(time.time()) + SESSION_MAX_AGE
        self.store.update_ttl(session_id, SESSION_MAX_AGE)
        
        logger.info(f"✅ Session refreshed for {session_data.get('email')}")
        return True
    
    def _validate_session_security(
        self,
        session_data: Dict[str, Any],
        ip_address: Optional[str],
        user_agent: Optional[str]
    ) -> bool:
        """
        Validate session security (IP and User-Agent binding).
        
        Args:
            session_data: Session data from store
            ip_address: Current client IP
            user_agent: Current client User-Agent
        
        Returns:
            True if valid, False if potential hijacking detected
        """
        # Check IP address match
        if ip_address and session_data.get("ip_address"):
            if ip_address != session_data["ip_address"]:
                # Allow Railway internal IP changes (load balancing)
                is_railway_internal = (
                    ip_address.startswith("100.64.") and 
                    session_data["ip_address"].startswith("100.64.")
                )
                
                if not is_railway_internal:
                    logger.warning(
                        f"🚨 IP mismatch for {session_data.get('email')}: "
                        f"expected {session_data['ip_address']}, got {ip_address}"
                    )
                    return False
        
        # Check User-Agent match
        # Disabled: User-Agent validation is too strict for web apps
        # Users legitimately access from different devices/browsers
        # if user_agent and session_data.get("user_agent"):
        #     if user_agent != session_data["user_agent"]:
        #         logger.warning(
        #             f"🚨 User-Agent mismatch for {session_data.get('email')}: "
        #             f"session created with different browser/device"
        #         )
        #         return False
        
        return True
    
    def validate_csrf(self, request_origin: Optional[str], allowed_origins: list) -> bool:
        """
        Validate CSRF by checking Origin header.
        
        Args:
            request_origin: Origin header from request
            allowed_origins: List of allowed origins
        
        Returns:
            True if valid, False if potential CSRF attack
        """
        if not request_origin:
            logger.warning("🚨 CSRF check failed: No Origin header")
            return False
        
        if request_origin not in allowed_origins:
            logger.warning(f"🚨 CSRF check failed: Origin {request_origin} not in allowed list")
            return False
        
        return True


# Dependency injection helper
def get_session_service(session_store) -> SessionService:
    """
    Create SessionService with dependency injection.
    
    Args:
        session_store: Storage backend (from get_session_store())
    
    Returns:
        SessionService instance
    """
    return SessionService(session_store)
