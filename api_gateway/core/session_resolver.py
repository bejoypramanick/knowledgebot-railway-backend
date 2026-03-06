"""
Session UUID to Numeric ID Resolver for API Gateway

Handles conversion of chat session UUIDs (e.g., "session_xxx") to numeric database IDs.
This resolver runs once at the API Gateway level, so internal services don't need to
perform lookups - they always receive numeric IDs.

Architecture:
- External API (UI) uses: UUID session IDs (e.g., "session_1772521413864_5o610dbd1")
- Internal services use: Numeric database IDs (e.g., 505)
- API Gateway translates UUID → Numeric ID once, on entry
- Internal services trust the numeric ID without further lookup
"""

from typing import Optional
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)


async def resolve_session_uuid_to_numeric_id(session_uuid: str) -> Optional[int]:
    """
    Resolve chat session UUID to numeric database ID.

    Uses Redis cache first (fast), falls back to database query.
    Caches result for 1 hour to avoid repeated lookups.

    Args:
        session_uuid: Session UUID like "session_1772521413864_5o610dbd1"

    Returns:
        Numeric session ID (e.g., 505) or None if not found
    """
    try:
        # Import here to avoid circular dependencies
        from shared.redis_pubsub_manager import get_pubsub_redis
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        # Step 1: Try Redis cache first (very fast)
        try:
            redis_client = await get_pubsub_redis()
            cache_key = f"session:uuid_to_id:{session_uuid}"
            cached_id = await redis_client.get(cache_key)
            if cached_id:
                numeric_id = int(cached_id)
                logger.debug(f"✅ Resolved {session_uuid} from Redis cache → {numeric_id}")
                return numeric_id
        except Exception as e:
            logger.debug(f"Redis lookup failed for {session_uuid}: {e}, falling back to DB")

        # Step 2: Query database
        try:
            async with get_db_session() as session:
                query = "SELECT id FROM chat_sessions WHERE session_id = :session_id LIMIT 1"
                result = await session.execute(text(query), {"session_id": session_uuid})
                row = result.mappings().first()

                if row:
                    numeric_id = row["id"]

                    # Step 3: Cache the mapping for future requests (TTL: 1 hour)
                    try:
                        redis_client = await get_pubsub_redis()
                        cache_key = f"session:uuid_to_id:{session_uuid}"
                        await redis_client.setex(cache_key, 3600, str(numeric_id))
                        logger.debug(f"💾 Cached {session_uuid} → {numeric_id} (TTL: 1h)")
                    except Exception as cache_error:
                        logger.warning(f"Failed to cache UUID mapping: {cache_error}")

                    logger.debug(f"✅ Resolved {session_uuid} from DB → {numeric_id}")
                    return numeric_id
                else:
                    logger.warning(f"⚠️ Session UUID {session_uuid} not found in database")
                    return None

        except Exception as e:
            logger.error(f"❌ Database lookup failed for {session_uuid}: {e}")
            return None

    except Exception as e:
        logger.error(f"❌ Error resolving session UUID {session_uuid}: {e}")
        return None


def extract_session_uuid_from_path(path: str) -> Optional[str]:
    """
    Extract session UUID from request path.

    Handles various URL patterns:
    - /api/v1/gateway/chatbot/chat/stream?session_id=session_xxx
    - /api/v1/gateway/configuration/admin/chat-sessions/session_xxx/...
    - /api/v1/gateway/configuration/customer/events/session_xxx

    Args:
        path: Request URL path

    Returns:
        Session UUID if found, None otherwise
    """
    # Look for session_xxx pattern in path
    import re
    match = re.search(r'(session_[a-zA-Z0-9_]+)', path)
    if match:
        return match.group(1)
    return None
