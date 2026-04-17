"""
Tenant-aware request middleware for internal services.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from shared.tenant_context import (
    reset_tenant_context,
    set_tenant_context,
)
from shared.internal_request_auth import has_identity_headers, verify_internal_request
from shared.widget_access import (
    LEGACY_WIDGET_TOKEN_SCOPE,
    WIDGET_EMBED_TOKEN_SCOPE,
    WIDGET_SESSION_TOKEN_SCOPE,
    extract_widget_access_token,
    verify_widget_access_token,
)


PUBLIC_WIDGET_ACCESS_PATHS = (
    "/api/v1/configuration/widgetConfig",
    "/api/v1/knowledgebase/files",
    "/api/v1/chatbot/chat/stream",
    "/api/v1/chatbot/chat/session",
)


def _supports_public_widget_access(request: Request) -> bool:
    path = request.url.path
    return any(path.startswith(prefix) for prefix in PUBLIC_WIDGET_ACCESS_PATHS)


def _widget_access_scopes_for_request(request: Request) -> tuple[str, ...]:
    path = request.url.path
    if path.startswith(
        (
            "/api/v1/configuration/widgetConfig",
            "/api/v1/chatbot/chat/stream",
            "/api/v1/chatbot/chat/session",
            "/api/v1/knowledgebase/files",
        )
    ):
        return (WIDGET_SESSION_TOKEN_SCOPE,)
    return (
        LEGACY_WIDGET_TOKEN_SCOPE,
        WIDGET_EMBED_TOKEN_SCOPE,
        WIDGET_SESSION_TOKEN_SCOPE,
    )


async def tenant_context_middleware(request: Request, call_next):
    internal_request_verified = verify_internal_request(request)
    request.state.internal_request_verified = internal_request_verified
    request.state.widget_access_verified = False
    request.state.widget_access_claims = None

    if has_identity_headers(request.headers) and not internal_request_verified:
        return JSONResponse(
            status_code=403,
            content={"detail": "Unsigned identity headers are not allowed"},
        )

    tenant_id = getattr(request.state, "tenant_id", None)
    tenant_slug = getattr(request.state, "tenant_slug", None)
    user_role_id = getattr(request.state, "user_role_id", None)
    user_email = getattr(request.state, "user_email", None)
    is_platform_admin = (
        request.headers.get("X-User-Is-Platform-Admin", "").lower() == "true"
    )

    if internal_request_verified:
        tenant_id = request.headers.get("X-Tenant-ID") or tenant_id
        tenant_slug = request.headers.get("X-Tenant-Slug") or tenant_slug
        user_role_id = request.headers.get("X-User-Role-ID") or user_role_id
        user_email = request.headers.get("X-User-Email") or user_email
    elif _supports_public_widget_access(request):
        widget_access_claims = verify_widget_access_token(
            extract_widget_access_token(request),
            expected_scopes=_widget_access_scopes_for_request(request),
        )
        if widget_access_claims:
            tenant_id = widget_access_claims.get("tenant_id") or tenant_id
            tenant_slug = widget_access_claims.get("tenant_slug") or tenant_slug
            request.state.widget_access_verified = True
            request.state.widget_access_claims = widget_access_claims

    request.state.tenant_id = tenant_id
    request.state.tenant_slug = tenant_slug
    request.state.user_role_id = user_role_id
    request.state.user_email = user_email

    tokens = set_tenant_context(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_role_id=user_role_id,
        user_email=user_email,
        is_platform_admin=is_platform_admin,
    )
    try:
        response = await call_next(request)
        return response
    finally:
        reset_tenant_context(tokens)
