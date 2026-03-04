"""
Session Store - Redis-based session management
Stores temporary session data in Redis for fast lookups
User data remains in Postgres database
"""
import os
import json
import redis
from typing import Optional, Dict, Any
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

# Global Redis client
_redis_client: Optional[redis.Redis] = None


def init_redis() -> redis.Redis:
    """
    Initialize Redis connection for session storage
    
    Uses existing Railway Redis instance via REDIS_URL environment variable
    Uses database 3 to isolate sessions from other data (0, 1, 2 already in use)
    
    REDIS_URL can specify database in two ways:
    1. In URL: redis://...@host:6379/3
    2. Via db parameter (if not in URL)
    
    Raises RuntimeError if Redis is not configured or connection fails.
    """
    global _redis_client
    
    if _redis_client is not None:
        logger.info("Redis client already initialized")
        return _redis_client
    
    # REDIS_URL is required - no fallback
    redis_url = os.getenv('REDIS_URL')
    
    if not redis_url:
        error_msg = (
            "REDIS_URL environment variable not set. "
            "Session storage requires Redis. "
            "Please configure REDIS_URL in Railway API Gateway service."
        )
        logger.error(f"❌ {error_msg}")
        raise RuntimeError(error_msg)
    
    try:
        # Check if database is specified in URL
        # If URL ends with /3, use that; otherwise default to database 3
        if redis_url.endswith('/3'):
            # Database already specified in URL
            _redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
            logger.info(f"✅ Redis connected successfully for session storage (database 3 from URL)")
        else:
            # Database not in URL, specify db=3
            _redis_client = redis.from_url(
                redis_url,
                db=3,  # Use database 3 for sessions
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30
            )
            logger.info(f"✅ Redis connected successfully for session storage (database 3 via parameter)")
        
        # Test connection
        _redis_client.ping()
        
        return _redis_client
        
    except redis.ConnectionError as e:
        error_msg = f"Failed to connect to Redis: {e}. Check REDIS_URL and ensure Redis service is running."
        logger.error(f"❌ {error_msg}")
        raise RuntimeError(error_msg)
    except Exception as e:
        error_msg = f"Error initializing Redis: {e}"
        logger.error(f"❌ {error_msg}")
        raise RuntimeError(error_msg)


def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client, initializing if needed"""
    if _redis_client is None:
        return init_redis()
    return _redis_client


class SessionStore:
    """
    Session storage using Redis database 3
    
    Redis databases in use:
    - Database 0: (your existing data)
    - Database 1: (your existing data)
    - Database 2: (your existing data)
    - Database 3: Sessions (isolated namespace)
    
    Requires REDIS_URL environment variable to be set.
    No fallback - fails fast if Redis is not configured.
    """
    
    def __init__(self):
        # Initialize Redis - will raise RuntimeError if not configured
        self.redis_client = get_redis_client()
        
        if not self.redis_client:
            raise RuntimeError(
                "Redis client initialization failed. "
                "REDIS_URL must be configured for session storage. "
                "No fallback available."
            )
        
        logger.info("✅ SessionStore initialized with Redis")
    
    def _get_key(self, session_id: str) -> str:
        """Get Redis key for session"""
        return f"session:{session_id}"
    
    def create(self, session_id: str, session_data: Dict[str, Any], ttl: int) -> bool:
        """
        Create a new session
        
        Args:
            session_id: Unique session identifier
            session_data: Session data to store
            ttl: Time to live in seconds
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Store in Redis with expiration
            key = self._get_key(session_id)
            value = json.dumps(session_data)
            self.redis_client.setex(key, ttl, value)
            logger.debug(f"✅ Session {session_id[:8]}... stored in Redis (TTL: {ttl}s)")
            return True
                
        except Exception as e:
            logger.error(f"❌ Error creating session: {e}")
            return False
    
    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session data by session ID
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session data if found, None otherwise
        """
        try:
            # Get from Redis
            key = self._get_key(session_id)
            value = self.redis_client.get(key)
            
            if value:
                session_data = json.loads(value)
                logger.debug(f"✅ Session {session_id[:8]}... retrieved from Redis")
                return session_data
            else:
                logger.debug(f"⚠️ Session {session_id[:8]}... not found in Redis")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting session: {e}")
            return None
    
    def delete(self, session_id: str) -> bool:
        """
        Delete a session
        
        Args:
            session_id: Session identifier
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            # Delete from Redis
            key = self._get_key(session_id)
            result = self.redis_client.delete(key)
            if result:
                logger.info(f"✅ Session {session_id[:8]}... deleted from Redis")
                return True
            else:
                logger.debug(f"⚠️ Session {session_id[:8]}... not found in Redis")
                return False
                    
        except Exception as e:
            logger.error(f"❌ Error deleting session: {e}")
            return False
    
    def update_ttl(self, session_id: str, ttl: int) -> bool:
        """
        Update session TTL (time to live)
        
        Args:
            session_id: Session identifier
            ttl: New time to live in seconds
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Update TTL in Redis
            key = self._get_key(session_id)
            result = self.redis_client.expire(key, ttl)
            if result:
                logger.debug(f"✅ Session {session_id[:8]}... TTL updated to {ttl}s")
                return True
            else:
                logger.debug(f"⚠️ Session {session_id[:8]}... not found for TTL update")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error updating session TTL: {e}")
            return False
    
    def get_all_for_user(self, uid: str) -> list[str]:
        """
        Get all session IDs for a user (for logout from all devices)
        
        Args:
            uid: User Firebase UID
            
        Returns:
            List of session IDs
        """
        try:
            session_ids = []
            
            # Scan Redis for all session keys
            for key in self.redis_client.scan_iter(match="session:*"):
                value = self.redis_client.get(key)
                if value:
                    session_data = json.loads(value)
                    if session_data.get("uid") == uid:
                        # Extract session_id from key (remove "session:" prefix)
                        session_id = key.replace("session:", "")
                        session_ids.append(session_id)
            
            logger.info(f"✅ Found {len(session_ids)} sessions for user {uid}")
            return session_ids
            
        except Exception as e:
            logger.error(f"❌ Error getting sessions for user: {e}")
            return []
    
    def delete_all_for_user(self, uid: str) -> int:
        """
        Delete all sessions for a user (logout from all devices)
        
        Args:
            uid: User Firebase UID
            
        Returns:
            Number of sessions deleted
        """
        try:
            session_ids = self.get_all_for_user(uid)
            deleted_count = 0
            
            for session_id in session_ids:
                if self.delete(session_id):
                    deleted_count += 1
            
            logger.info(f"✅ Deleted {deleted_count} sessions for user {uid}")
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ Error deleting sessions for user: {e}")
            return 0
    
    def health_check(self) -> bool:
        """
        Check if session store is healthy
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            self.redis_client.ping()
            return True
        except Exception as e:
            logger.error(f"❌ Session store health check failed: {e}")
            return False


# Global session store instance
_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """Get global session store instance"""
    global _session_store
    
    if _session_store is None:
        _session_store = SessionStore()
    
    return _session_store
