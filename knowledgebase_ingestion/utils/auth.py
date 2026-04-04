"""
Authentication utilities for knowledgebase ingestion
"""
from typing import Tuple, Optional
from fastapi import Request, HTTPException
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from shared.log_sanitizer import hash_pii
from shared.tenant_context import get_current_user_role_id

logger = get_otel_logger("auth", "knowledgebase-ingestion")


def extract_user_from_request(request: Request) -> Tuple[str, Optional[str]]:
    """
    Extract user information from request headers.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Tuple of (user_email, user_id)
    """
    try:
        # Extract user email from headers (set by API Gateway)
        user_email = request.headers.get("x-user-email")
        user_id = request.headers.get("x-user-id")
        
        if not user_email:
            logger.warning("Missing x-user-email header in request")
            raise HTTPException(status_code=401, detail="Authentication required")
        
        return user_email, user_id
        
    except Exception as e:
        logger.error(f"Error extracting user from request: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def get_user_role_id_from_email(user_email: str) -> Optional[str]:
    """
    Look up user_role_id from user_role_mapping table using email.
    Joins with users table to match email to user_id.

    Args:
        user_email: User's email address

    Returns:
        user_role_id if found, None otherwise
    """
    try:
        current_user_role_id = get_current_user_role_id()
        if current_user_role_id:
            return current_user_role_id

        from sqlalchemy import text

        query = """
            SELECT urm.user_role_id
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            WHERE u.email = :email
            LIMIT 1
        """

        async with get_db_session() as session:
            result = await session.execute(text(query), {"email": user_email})
            user_role_id = result.scalar()

            if user_role_id:
                logger.info(f"✅ Found user_role_id={user_role_id} for user_hash={hash_pii(user_email)}")
            else:
                logger.warning(f"⚠️ No user_role_id found for user_hash={hash_pii(user_email)}")

            return user_role_id

    except Exception as e:
        logger.error(f"❌ Error looking up user_role_id for user_hash={hash_pii(user_email)}: {e}", exc_info=True)
        return None


def validate_user_access(user_email: str, resource_owner_email: str) -> bool:
    """
    Validate if user has access to resource.
    
    Args:
        user_email: Current user email
        resource_owner_email: Resource owner email
        
    Returns:
        True if user has access, False otherwise
    """
    # Simple email comparison - can be enhanced with role-based access
    return user_email == resource_owner_email


def get_user_context(request: Request) -> dict:
    """
    Get user context from request.
    
    Args:
        request: FastAPI Request object
        
    Returns:
        Dictionary with user context
    """
    user_email, user_id = extract_user_from_request(request)
    
    return {
        "user_email": user_email,
        "user_id": user_id,
        "authenticated": True
    }
