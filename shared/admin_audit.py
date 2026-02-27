"""
Admin Action Audit Decorator and Context Manager
Provides reusable audit logging for all admin operations.
"""

import uuid
import time
import json
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, Callable
from functools import wraps
from datetime import datetime

from shared.otel_logger import (
    get_otel_logger,
    get_admin_session_id,
    get_admin_email,
    get_admin_role
)

logger = get_otel_logger("admin_audit", "configuration")


class ActionAudit:
    """Context manager for auditing admin actions.

    Tracks execution time, success/failure, and automatically logs to DB.

    Usage:
        async with ActionAudit(
            action_type="config.chatbot.update",
            action_category="config",
            resource_type="chatbot_config",
            resource_id="12345"
        ):
            # Perform action
            result = await service.save_config(config)
    """

    def __init__(
        self,
        action_type: str,
        action_category: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        http_method: Optional[str] = None,
        endpoint: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ):
        self.action_type = action_type
        self.action_category = action_category
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.http_method = http_method
        self.endpoint = endpoint
        self.ip_address = ip_address
        self.user_agent = user_agent

        self.action_id = str(uuid.uuid4())
        self.start_time = None
        self.end_time = None
        self.duration_ms = 0
        self.success = False
        self.error_message = None
        self.error_code = None
        self.response_status = 500

    async def __aenter__(self):
        """Start action tracking."""
        self.start_time = time.time()
        logger.info(f"📝 Action started: {self.action_type}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """End action tracking and log to DB."""
        self.end_time = time.time()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)

        if exc_type is None:
            self.success = True
            self.response_status = 200
            logger.info(f"✅ Action completed: {self.action_type} ({self.duration_ms}ms)")
        else:
            self.success = False
            self.response_status = 500
            self.error_message = str(exc_val)
            self.error_code = exc_type.__name__
            logger.error(f"❌ Action failed: {self.action_type} | Error: {exc_val}")

        # Log to database asynchronously (non-blocking)
        try:
            asyncio.create_task(self._log_to_database())
        except RuntimeError:
            # If no event loop, run synchronously
            await self._log_to_database()

        # Return False to propagate exception if any
        return False

    async def _log_to_database(self):
        """Insert action log into admin_actions table."""
        try:
            admin_session_id = get_admin_session_id()
            admin_email = get_admin_email()
            admin_role = get_admin_role()

            # Skip logging if not in admin context
            if not admin_session_id or not admin_email:
                logger.warning(f"⚠️ Skipping action audit: no admin context for {self.action_type}")
                return

            # Get DB connection and log action
            from shared.db import get_db_connection

            async with get_db_connection() as conn:
                # First, get the admin session ID from DB to link records
                session_query = """
                    SELECT id FROM admin_sessions
                    WHERE session_id = $1
                    LIMIT 1
                """
                session_record = await conn.fetchrow(session_query, admin_session_id)

                if not session_record:
                    logger.warning(f"⚠️ Admin session not found in DB: {admin_session_id}")
                    return

                session_db_id = session_record["id"]

                # Insert action record
                action_query = """
                    INSERT INTO admin_actions (
                        action_id, session_id, user_role_id, email, role_name,
                        action_type, action_category, http_method, endpoint,
                        resource_type, resource_id, duration_ms, success,
                        error_message, error_code, response_status,
                        ip_address, user_agent, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
                """

                action_values = (
                    self.action_id,
                    session_db_id,
                    0,  # user_role_id placeholder (will be fetched from session if needed)
                    admin_email,
                    admin_role,
                    self.action_type,
                    self.action_category,
                    self.http_method,
                    self.endpoint,
                    self.resource_type,
                    self.resource_id,
                    self.duration_ms,
                    self.success,
                    self.error_message,
                    self.error_code,
                    self.response_status,
                    self.ip_address,
                    self.user_agent,
                    datetime.utcnow().isoformat(),
                )

                try:
                    await conn.execute(action_query, *action_values)
                    logger.info(f"✅ Action logged to DB: {self.action_id}")

                    # Increment session action count
                    update_query = """
                        UPDATE admin_sessions
                        SET action_count = action_count + 1,
                            last_activity_at = $1
                        WHERE id = $2
                    """
                    await conn.execute(update_query, datetime.utcnow().isoformat(), session_db_id)

                except Exception as db_error:
                    logger.error(f"❌ Failed to log action to DB: {db_error}")

        except Exception as e:
            # Log error but don't raise - auditing shouldn't break main flow
            logger.error(f"❌ Audit logging error: {e}")


def audit_action(
    action_type: str,
    action_category: str,
    resource_type: Optional[str] = None,
    resource_id_param: Optional[str] = None,
) -> Callable:
    """
    Decorator for audit logging admin actions.

    Usage:
        @audit_action(
            action_type="config.chatbot.update",
            action_category="config",
            resource_type="chatbot_config",
            resource_id_param="config_id"  # Name of the parameter
        )
        async def save_chatbot_config(config: ChatbotConfigRequest, config_id: str = ""):
            ...

    Args:
        action_type: Hierarchical action identifier (e.g., "config.chatbot.update")
        action_category: Category for grouping (config, user_management, chat_management, etc.)
        resource_type: Type of resource being modified (optional)
        resource_id_param: Name of the parameter containing resource ID (optional)
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Extract resource_id from kwargs if specified
            resource_id = None
            if resource_id_param:
                resource_id = kwargs.get(resource_id_param, None)

            # Extract request and other metadata
            request = None
            ip_address = None
            user_agent = None
            http_method = None
            endpoint = None

            # Try to find Request object in args or kwargs
            from fastapi import Request
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request and "request" in kwargs:
                request = kwargs["request"]

            if request:
                ip_address = request.client.host if request.client else None
                user_agent = request.headers.get("user-agent")
                http_method = request.method
                endpoint = request.url.path

            # Run with audit context
            async with ActionAudit(
                action_type=action_type,
                action_category=action_category,
                resource_type=resource_type,
                resource_id=resource_id,
                http_method=http_method,
                endpoint=endpoint,
                ip_address=ip_address,
                user_agent=user_agent,
            ) as audit:
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, run in event loop
            import asyncio
            resource_id = None
            if resource_id_param:
                resource_id = kwargs.get(resource_id_param, None)

            request = None
            ip_address = None
            user_agent = None
            http_method = None
            endpoint = None

            from fastapi import Request
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request and "request" in kwargs:
                request = kwargs["request"]

            if request:
                ip_address = request.client.host if request.client else None
                user_agent = request.headers.get("user-agent")
                http_method = request.method
                endpoint = request.url.path

            # Can't use async context manager in sync function
            # Just log the action without the context manager
            action_audit = ActionAudit(
                action_type=action_type,
                action_category=action_category,
                resource_type=resource_type,
                resource_id=resource_id,
                http_method=http_method,
                endpoint=endpoint,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            action_audit.start_time = time.time()

            try:
                result = func(*args, **kwargs)
                action_audit.end_time = time.time()
                action_audit.success = True
                return result
            except Exception as e:
                action_audit.end_time = time.time()
                action_audit.success = False
                action_audit.error_message = str(e)
                action_audit.error_code = type(e).__name__
                raise
            finally:
                action_audit.duration_ms = int((action_audit.end_time - action_audit.start_time) * 1000)
                # Try to log asynchronously
                try:
                    asyncio.create_task(action_audit._log_to_database())
                except RuntimeError:
                    # No event loop, skip async logging
                    pass

        # Return async or sync wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator
