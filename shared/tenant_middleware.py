"""
Tenant-aware request middleware for internal services.
"""
from __future__ import annotations

from fastapi import Request

from shared.tenant_context import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_SLUG,
    reset_tenant_context,
    set_tenant_context,
)


PUBLIC_TENANT_FALLBACK_PATHS = (
    "/api/v1/configuration/widgetConfig",
    "/api/v1/knowledgebase/files",
    "/api/v1/chatbot/chat/stream",
    "/api/v1/chatbot/chat/session",
)


def _should_use_public_fallback(request: Request) -> bool:
    path = request.url.path
    return any(path.startswith(prefix) for prefix in PUBLIC_TENANT_FALLBACK_PATHS)


async def tenant_context_middleware(request: Request, call_next):
    tenant_id = (
        request.headers.get("X-Tenant-ID")
        or request.query_params.get("tenant_id")
        or getattr(request.state, "tenant_id", None)
    )
    tenant_slug = (
        request.headers.get("X-Tenant-Slug")
        or request.query_params.get("tenant_slug")
        or getattr(request.state, "tenant_slug", None)
    )
    user_role_id = (
        request.headers.get("X-User-Role-ID")
        or getattr(request.state, "user_role_id", None)
    )
    user_email = (
        request.headers.get("X-User-Email")
        or getattr(request.state, "user_email", None)
    )

    if not tenant_id and _should_use_public_fallback(request):
        tenant_id = DEFAULT_TENANT_ID
        tenant_slug = tenant_slug or DEFAULT_TENANT_SLUG

    request.state.tenant_id = tenant_id
    request.state.tenant_slug = tenant_slug
    request.state.user_role_id = user_role_id
    request.state.user_email = user_email

    tokens = set_tenant_context(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_role_id=user_role_id,
        user_email=user_email,
    )
    try:
        response = await call_next(request)
        return response
    finally:
        reset_tenant_context(tokens)
