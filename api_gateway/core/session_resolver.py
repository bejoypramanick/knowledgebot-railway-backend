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

Uses Redis DB 5 for session UUID→numeric ID cache (dedicated, separate from Pub/Sub DB 3).
"""

from typing import Optional
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)


async def resolve_session_uuid_to_numeric_id(session_uuid: str) -> Optional[int]:
    """
    Resolve chat session UUID to numeric database ID.

    Uses Redis DB 5 cache first (fast), falls back to database query.
    Caches result for 1 hour to avoid repeated lookups.

    Args:
        session_uuid: Session UUID like "session_1772521413864_5o610dbd1"

    Returns:
        Numeric session ID (e.g., 505) or None if not found
    """
    try:
        from shared.redis_session_id_cache import get_numeric_id, set_numeric_id
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        # Step 1: Try Redis DB 5 cache first (very fast)
        try:
            cached_id = await get_numeric_id(session_uuid)
            if cached_id is not None:
                logger.debug(f"Resolved {session_uuid} from Redis cache (DB 5) -> {cached_id}")
                return cached_id
        except Exception as e:
            logger.debug(f"Redis DB 5 lookup failed for {session_uuid}: {e}, falling back to DB")

        # Step 2: Query database
        try:
            async with get_db_session() as session:
                query = "SELECT id FROM chat_sessions WHERE session_id = :session_id LIMIT 1"
                result = await session.execute(text(query), {"session_id": session_uuid})
                row = result.mappings().first()

                if row:
                    numeric_id = row["id"]

                    # Step 3: Cache the mapping in Redis DB 5 (TTL: 1 hour)
                    try:
                        await set_numeric_id(session_uuid, numeric_id)
                        logger.debug(f"Cached {session_uuid} -> {numeric_id} in Redis DB 5")
                    except Exception as cache_error:
                        logger.warning(f"Failed to cache UUID mapping: {cache_error}")

                    logger.debug(f"Resolved {session_uuid} from DB -> {numeric_id}")
                    return numeric_id
                else:
                    logger.warning(f"Session UUID {session_uuid} not found in database")
                    return None

        except Exception as e:
            logger.error(f"Database lookup failed for {session_uuid}: {e}")
            return None

    except Exception as e:
        logger.error(f"Error resolving session UUID {session_uuid}: {e}")
        return None


def extract_session_uuid_from_cookie(request) -> Optional[str]:
    """
    Extract session UUID from httpOnly cookie.

    Session UUID should be stored in httpOnly, Secure, SameSite cookie named 'chatbot_session_id'.
    This prevents exposure in URL paths, query params, or request bodies.

    Args:
        request: FastAPI Request object

    Returns:
        Session UUID if found in cookie, None otherwise
    """
    try:
        session_uuid = request.cookies.get('chatbot_session_id')
        if session_uuid:
            logger.debug(f"Extracted session UUID from cookie: {session_uuid[:20]}...")
            return session_uuid
        else:
            logger.debug("No session UUID in chatbot_session_id cookie")
            return None
    except Exception as e:
        logger.warning(f"Error extracting session UUID from cookie: {e}")
        return None


def extract_session_uuid_from_path(path: str) -> Optional[str]:
    """
    DEPRECATED: Extract session UUID from request path.

    Session UUID should come from httpOnly cookie, not URL path.
    This method is kept for backward compatibility only.

    Args:
        path: Request URL path

    Returns:
        Session UUID if found, None otherwise
    """
    # Look for session_xxx pattern in path (fallback only)
    import re
    match = re.search(r'(session_[a-zA-Z0-9_]+)', path)
    if match:
        logger.warning(f"Session UUID found in URL path (should use cookie): {match.group(1)[:20]}...")
        return match.group(1)
    return None
