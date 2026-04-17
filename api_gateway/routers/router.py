"""
Consolidated API Gateway Router
All API Gateway endpoints in one file for easier debugging
"""

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.responses import StreamingResponse, Response, JSONResponse
from typing import Dict, Any, Optional
from httpx import AsyncClient
import httpx
import asyncio
from urllib.parse import urlencode
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..core.firebase_auth import (
    verify_firebase_token,
    get_user_by_uid as get_user_from_firebase,
)
from ..core.config import get_settings
from ..core.session_store import get_session_store
from ..services.session_service import get_session_service
from shared.otel_logger import get_otel_logger
from shared.internal_request_auth import add_internal_request_signature
from shared.widget_access import (
    LEGACY_WIDGET_TOKEN_SCOPE,
    WIDGET_EMBED_TOKEN_SCOPE,
    WIDGET_SESSION_TOKEN_SCOPE,
    extract_widget_access_token,
    extract_widget_parent_origin,
    issue_widget_session_token,
    is_widget_origin_allowed,
    verify_widget_access_token,
)

logger = get_otel_logger("api_gateway.routers.router", "api-gateway")
router = APIRouter()

# Initialize SlowAPI rate limiter for request-count based limiting
limiter = Limiter(key_func=get_remote_address)
INTERNAL_CALLER_ID = "api-gateway"


def _remove_untrusted_identity_headers(headers: Dict[str, str]) -> None:
    for header_name in (
        "X-User-UID",
        "X-User-Email",
        "X-User-Name",
        "X-User-Role",
        "X-User-Role-ID",
        "X-Tenant-ID",
        "X-Tenant-Slug",
        "X-Widget-Access-Token",
    ):
        headers.pop(header_name, None)
        headers.pop(header_name.lower(), None)


def _sign_internal_headers(
    headers: Dict[str, str], method: str, path_or_url: str
) -> Dict[str, str]:
    return add_internal_request_signature(
        headers=headers,
        method=method,
        path_or_url=path_or_url,
        caller=INTERNAL_CALLER_ID,
    )


def _append_query_params(url: str, query_params) -> str:
    if not query_params:
        return url

    encoded_query = urlencode(list(query_params.multi_items()))
    if not encoded_query:
        return url

    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{encoded_query}"


def _apply_public_widget_context(
    request: Request,
    expected_scopes: Optional[tuple[str, ...]] = None,
) -> Optional[Dict[str, Any]]:
    widget_claims = verify_widget_access_token(
        extract_widget_access_token(request),
        expected_scopes=expected_scopes,
    )
    if not widget_claims:
        return None

    request.state.tenant_id = widget_claims.get("tenant_id")
    request.state.tenant_slug = widget_claims.get("tenant_slug")
    request.state.widget_access_verified = True
    request.state.widget_access_claims = widget_claims
    return widget_claims


def _apply_authenticated_session_context(request: Request) -> bool:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        return False

    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    session_store = get_session_store()
    session_service = get_session_service(session_store)
    session_data = session_service.get_session(
        session_id,
        ip_address,
        user_agent,
        validate_security=True,
    )
    if not session_data:
        return False

    request.state.user = session_data
    request.state.user_uid = session_data.get("uid")
    request.state.user_email = session_data.get("email")
    request.state.user_name = session_data.get("name")
    request.state.user_role = session_data.get("role")
    request.state.user_role_id = session_data.get("active_user_role_id")
    request.state.tenant_id = session_data.get("active_tenant_id")
    request.state.tenant_slug = session_data.get("active_tenant_slug")
    return True


def _require_public_widget_context(
    request: Request,
    expected_scopes: Optional[tuple[str, ...]] = None,
) -> Dict[str, Any]:
    widget_claims = _apply_public_widget_context(
        request, expected_scopes=expected_scopes
    )
    if not widget_claims:
        raise HTTPException(
            status_code=403, detail="Valid widget access token is required"
        )
    return widget_claims


async def check_config_service_with_retry(
    config_service_url: str,
    headers: Dict[str, str] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    Check configuration service with retry logic for connection failures.
    Returns config dict or None if all attempts fail.
    """
    retry_delays = [0.5, 1.0]  # Quick retries for better UX

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                signed_headers = dict(headers or {})
                _sign_internal_headers(
                    signed_headers,
                    method="GET",
                    path_or_url=f"{config_service_url}/api/v1/configuration/widgetConfig",
                )
                response = await client.get(
                    f"{config_service_url}/api/v1/configuration/widgetConfig",
                    headers=signed_headers or None,
                    timeout=3.0,
                )

                if response.status_code == 200:
                    payload = response.json()
                    if isinstance(payload, dict) and isinstance(
                        payload.get("data"), dict
                    ):
                        return payload["data"]
                    return payload

        except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
            if attempt < max_retries - 1:
                delay = retry_delays[attempt]
                logger.warning(
                    f"⚠️ Config service connection failed (attempt {attempt + 1}/{max_retries}), retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
                continue
            else:
                logger.error(
                    f"❌ Config service unavailable after {max_retries} attempts"
                )
                return None
        except Exception as e:
            logger.error(f"❌ Unexpected error checking config service: {e}")
            return None

    return None


# =================================
# WINDOW-LOAD CHAT VALIDATION ENDPOINT
# =================================


@router.get("/chatbot/validate-chat")
@limiter.limit("100/minute")
async def validate_chat_window_load(request: Request):
    """
    Window-load chat validation endpoint.

    Performs chat availability and domain validation at widget initialization time.
    Results are cached in Redis to avoid per-message validation overhead.
    Pre-creates session for first message.

    Returns:
        {
            "ready": bool,
            "chat_enabled": bool,
            "domain_authorized": bool,
            "session_id": str | null,
            "widget_session_token": str | null,
            "reason": str | null
        }
    """
    try:
        from shared.redis_widget_config_cache import (
            get_allowed_widget_origins,
            get_display_chatbot,
            set_allowed_widget_origins,
            set_display_chatbot,
        )
        import uuid

        correlation_id = str(uuid.uuid4())
        logger.info(f"[{correlation_id}] Chat validation request from window load")
        widget_claims = _require_public_widget_context(
            request,
            expected_scopes=(
                LEGACY_WIDGET_TOKEN_SCOPE,
                WIDGET_EMBED_TOKEN_SCOPE,
                WIDGET_SESSION_TOKEN_SCOPE,
            ),
        )
        tenant_id = widget_claims.get("tenant_id")
        tenant_slug = widget_claims.get("tenant_slug")
        parent_origin = widget_claims.get(
            "parent_origin"
        ) or extract_widget_parent_origin(request)
        claimed_parent_origin = widget_claims.get("parent_origin")
        tenant_headers = {}
        if tenant_id:
            tenant_headers["X-Tenant-ID"] = tenant_id
        if tenant_slug:
            tenant_headers["X-Tenant-Slug"] = tenant_slug

        logger.info(f"[{correlation_id}] ✅ Widget access token authorized")

        if not parent_origin:
            logger.warning(f"[{correlation_id}] ❌ Widget parent origin missing")
            return {
                "ready": False,
                "chat_enabled": False,
                "domain_authorized": False,
                "session_id": None,
                "widget_session_token": None,
                "reason": "Embedding origin could not be determined. Set the iframe referrer policy to origin.",
            }
        if claimed_parent_origin and claimed_parent_origin != parent_origin:
            logger.warning(
                f"[{correlation_id}] ❌ Widget parent origin mismatch for runtime token"
            )
            return {
                "ready": False,
                "chat_enabled": False,
                "domain_authorized": False,
                "session_id": None,
                "widget_session_token": None,
                "reason": "Embedding origin does not match the approved widget session",
            }

        # Step 2: Check chat enabled status (Redis cache first, then config service)
        tenant_cache_key = tenant_id or tenant_slug
        chat_enabled = await get_display_chatbot(tenant_id=tenant_cache_key)
        allowed_origins = await get_allowed_widget_origins(tenant_id=tenant_cache_key)

        if chat_enabled is None or allowed_origins is None:
            logger.info(
                f"[{correlation_id}] Cache MISS for widget access controls, fetching from config service..."
            )
            config_service_url = "http://configuration.railway.internal:8080"
            config = await check_config_service_with_retry(
                config_service_url, headers=tenant_headers or None
            )

            if config:
                chat_enabled = config.get("display_chatbot", True)
                allowed_origins = (
                    config.get("allowed_origins", [])
                    if isinstance(config, dict)
                    else []
                )
                await set_display_chatbot(chat_enabled, tenant_id=tenant_cache_key)
                await set_allowed_widget_origins(
                    allowed_origins, tenant_id=tenant_cache_key
                )
                logger.info(
                    f"[{correlation_id}] ✅ Config service returned display_chatbot={chat_enabled} "
                    f"and {len(allowed_origins)} allowed origin(s), cached"
                )
            else:
                logger.warning(
                    f"[{correlation_id}] ⚠️ Config service unavailable, denying widget bootstrap"
                )
                return {
                    "ready": False,
                    "chat_enabled": False,
                    "domain_authorized": False,
                    "session_id": None,
                    "widget_session_token": None,
                    "reason": "Widget security policy could not be loaded",
                }
        else:
            logger.info(
                f"[{correlation_id}] ✅ Cache HIT: display_chatbot={chat_enabled}, "
                f"{len(allowed_origins)} allowed origin(s)"
            )

        if not chat_enabled:
            logger.info(f"[{correlation_id}] ❌ Chat is disabled")
            return {
                "ready": False,
                "chat_enabled": False,
                "domain_authorized": True,
                "session_id": None,
                "widget_session_token": None,
                "reason": "Chat is currently disabled",
            }

        if not allowed_origins:
            logger.warning(
                f"[{correlation_id}] ❌ No allowed widget origins configured"
            )
            return {
                "ready": False,
                "chat_enabled": True,
                "domain_authorized": False,
                "session_id": None,
                "widget_session_token": None,
                "reason": "No allowed widget origins are configured for this tenant",
            }

        if not is_widget_origin_allowed(parent_origin, allowed_origins):
            logger.warning(
                f"[{correlation_id}] ❌ Widget origin '{parent_origin}' is not allowed "
                f"for tenant '{tenant_id or tenant_slug}'"
            )
            return {
                "ready": False,
                "chat_enabled": True,
                "domain_authorized": False,
                "session_id": None,
                "widget_session_token": None,
                "reason": "This website is not authorized to use the widget",
            }

        # Step 3: Warm up downstream services (chatbot orchestration + configuration)
        # This ensures serverless containers are ready before the user sends their first message
        import httpx

        settings = get_settings()

        service_checks = {
            "chatbot_orchestration": f"{settings.chatbot_orchestration_url}/api/v1/chatbot/health",
            "configuration": f"{settings.configuration_service_url}/api/v1/configuration/health",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            for service_name, health_url in service_checks.items():
                try:
                    resp = await client.get(health_url)
                    if resp.status_code == 200:
                        logger.info(f"[{correlation_id}] ✅ {service_name} is healthy")
                    else:
                        logger.error(
                            f"[{correlation_id}] ❌ {service_name} health check failed: {resp.status_code}"
                        )
                        return {
                            "ready": False,
                            "chat_enabled": True,
                            "domain_authorized": True,
                            "session_id": None,
                            "widget_session_token": None,
                            "reason": f"Service {service_name} is not ready (status {resp.status_code})",
                        }
                except Exception as svc_err:
                    logger.error(
                        f"[{correlation_id}] ❌ {service_name} unreachable: {svc_err}"
                    )
                    return {
                        "ready": False,
                        "chat_enabled": True,
                        "domain_authorized": True,
                        "session_id": None,
                        "widget_session_token": None,
                        "reason": f"Service {service_name} is not reachable",
                    }

        # Step 4: Create session with PG18 database-generated UUIDv7 (via chatbot_orchestration service)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                session_response = await client.post(
                    f"{settings.chatbot_orchestration_url}/api/v1/chatbot/chat/session",
                    json={"agent_id": "default"},
                    headers=_sign_internal_headers(
                        dict(tenant_headers),
                        method="POST",
                        path_or_url=f"{settings.chatbot_orchestration_url}/api/v1/chatbot/chat/session",
                    ),
                )

                if session_response.status_code != 200:
                    logger.error(
                        f"[{correlation_id}] ❌ Session creation failed: {session_response.status_code}"
                    )
                    return {
                        "ready": False,
                        "chat_enabled": True,
                        "domain_authorized": True,
                        "session_id": None,
                        "widget_session_token": None,
                        "reason": f"Failed to create session (status {session_response.status_code})",
                    }

                session_data = session_response.json()
                session_id = session_data.get("session_id")

                if not session_id:
                    logger.error(
                        f"[{correlation_id}] ❌ Session creation returned no session_id"
                    )
                    return {
                        "ready": False,
                        "chat_enabled": True,
                        "domain_authorized": True,
                        "session_id": None,
                        "widget_session_token": None,
                        "reason": "Failed to generate session ID",
                    }

                logger.info(
                    f"[{correlation_id}] ✅ Session created with PG18 UUIDv7: {session_id}"
                )
        except Exception as session_err:
            logger.error(f"[{correlation_id}] ❌ Session creation error: {session_err}")
            return {
                "ready": False,
                "chat_enabled": True,
                "domain_authorized": True,
                "session_id": None,
                "widget_session_token": None,
                "reason": f"Failed to create session: {str(session_err)}",
            }

        widget_session_token = issue_widget_session_token(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            parent_origin=parent_origin,
        )

        return {
            "ready": True,
            "chat_enabled": True,
            "domain_authorized": True,
            "session_id": session_id,
            "widget_session_token": widget_session_token,
            "reason": None,
        }

    except Exception as e:
        logger.error(f"Validation endpoint error: {e}", exc_info=True)
        return {
            "ready": False,
            "chat_enabled": False,
            "domain_authorized": False,
            "session_id": None,
            "widget_session_token": None,
            "reason": f"Chat initialization failed: {str(e)}",
        }


# =================================
# FIREBASE AUTHENTICATION ENDPOINTS
# =================================


@router.post("/auth/verify")
@limiter.limit("100/minute")
async def verify_auth_token(request: Request):
    """Verify Firebase authentication token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Missing or invalid authorization header"
            )

        token = auth_header.split(" ")[1]
        user_data = verify_firebase_token(token)

        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {"success": True, "user": user_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        raise HTTPException(status_code=500, detail=f"Error verifying token: {str(e)}")


# =================================
# SSE (Server-Sent Events) ENDPOINTS
# =================================


def _prepare_sse_proxy_headers(request: Request) -> dict:
    """Prepare headers for SSE proxy requests to internal services.

    Strips hop-by-hop headers and encoding headers that break SSE proxying:
    - Accept-Encoding: prevents compressed responses that proxy can't decompress
    - Connection/Keep-Alive: hop-by-hop headers not meant for proxy-to-backend
    - Host/Cookie: internal routing headers
    """
    headers = dict(request.headers)
    # Strip headers that break SSE proxying
    for h in [
        "host",
        "cookie",
        "accept-encoding",
        "connection",
        "keep-alive",
        "transfer-encoding",
        "upgrade",
        "sec-websocket-key",
        "sec-websocket-version",
        "sec-websocket-extensions",
    ]:
        headers.pop(h, None)
    _remove_untrusted_identity_headers(headers)
    # Force identity encoding (no compression) for SSE
    headers["accept-encoding"] = "identity"
    _inject_identity_headers(request, headers)

    return headers


def _inject_identity_headers(request: Request, headers: Dict[str, str]) -> None:
    """Forward authenticated user and active tenant context to internal services."""
    _remove_untrusted_identity_headers(headers)
    request_tenant_id = getattr(request.state, "tenant_id", None)
    request_tenant_slug = getattr(request.state, "tenant_slug", None)
    request_user_role_id = getattr(request.state, "user_role_id", None)
    request_user_email = getattr(request.state, "user_email", None)

    # Forward auth context if available
    if hasattr(request.state, "user"):
        headers["X-User-UID"] = request.state.user.get("uid") or ""
        headers["X-User-Email"] = request.state.user.get("email") or ""
        headers["X-User-Name"] = request.state.user.get("name") or ""
        headers["X-User-Role"] = request.state.user.get("role") or ""
        request_user_email = request.state.user.get("email", "") or request_user_email

    if request_tenant_id:
        headers["X-Tenant-ID"] = request_tenant_id
    if request_tenant_slug:
        headers["X-Tenant-Slug"] = request_tenant_slug
    if request_user_role_id:
        headers["X-User-Role-ID"] = request_user_role_id
    if request_user_email:
        headers["X-User-Email"] = request_user_email


@router.get("/configuration/admin/events")
async def proxy_admin_events_sse(request: Request):
    """
    Proxy SSE endpoint for admin/agent events.
    SSE requires special handling - no timeout, streaming response.
    """
    try:
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/admin/events"

        logger.info(f"🔄 Proxying SSE stream to: {full_url}")

        headers = _prepare_sse_proxy_headers(request)
        _sign_internal_headers(headers, method="GET", path_or_url=full_url)
        if hasattr(request.state, "user"):
            logger.info(
                f"✅ Forwarding user headers for SSE: {request.state.user.get('email')}"
            )
        else:
            logger.warning("⚠️ No user found in request.state - authentication may fail")

        # Connection timeout 10s, but no read timeout (SSE streams indefinitely)
        sse_timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)

        async def event_stream():
            try:
                logger.info(f"📡 Starting httpx stream for admin SSE")
                async with httpx.AsyncClient(timeout=sse_timeout) as client:
                    async with client.stream(
                        "GET", full_url, headers=headers
                    ) as response:
                        logger.info(
                            f"📡 httpx stream connected, status: {response.status_code}"
                        )
                        async for chunk in response.aiter_bytes():
                            yield chunk
                        logger.info(f"📡 httpx stream ended for admin SSE")
            except httpx.ConnectError as e:
                logger.error(f"❌ Cannot connect to config service for admin SSE: {e}")
                yield f"event: error\ndata: Connection to backend failed\n\n".encode()
            except httpx.ConnectTimeout as e:
                logger.error(f"❌ Connection timeout for admin SSE: {e}")
                yield f"event: error\ndata: Backend connection timeout\n\n".encode()
            except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                # Client disconnected - this is expected and normal, log at debug level
                logger.debug(
                    f"🔌 Client disconnected from admin SSE stream: {type(e).__name__}"
                )
            except Exception as e:
                # Only log unexpected errors
                error_msg = str(e)
                if (
                    "peer closed connection" not in error_msg.lower()
                    and "incomplete chunked read" not in error_msg.lower()
                ):
                    logger.error(f"❌ Error in SSE stream: {e}")
                else:
                    logger.debug(f"🔌 Client disconnection during SSE stream: {e}")

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        logger.error(f"❌ Error setting up SSE proxy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configuration/customer/events")
async def proxy_customer_events_sse(
    request: Request, session_id: str = Query(..., description="Session UUID")
):
    """
    Proxy SSE endpoint for customer events.
    SSE requires special handling - no timeout, streaming response.
    Session ID comes from query parameter.
    """
    try:
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/customer/events?session_id={session_id}"

        logger.info(
            f"🔄 Proxying customer SSE stream to: {full_url} (session: {session_id})"
        )

        headers = _prepare_sse_proxy_headers(request)
        _sign_internal_headers(headers, method="GET", path_or_url=full_url)

        # Connection timeout 10s, but no read timeout (SSE streams indefinitely)
        sse_timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)

        async def event_stream():
            try:
                logger.info(f"📡 Starting httpx stream for session {session_id}")
                async with httpx.AsyncClient(timeout=sse_timeout) as client:
                    async with client.stream(
                        "GET", full_url, headers=headers
                    ) as response:
                        logger.info(
                            f"📡 httpx stream connected, status: {response.status_code}"
                        )
                        async for chunk in response.aiter_bytes():
                            yield chunk
                        logger.info(f"📡 httpx stream ended for session {session_id}")
            except httpx.ConnectError as e:
                logger.error(
                    f"❌ Cannot connect to config service for customer SSE ({session_id}): {e}"
                )
                yield f"event: error\ndata: Connection to backend failed\n\n".encode()
            except httpx.ConnectTimeout as e:
                logger.error(
                    f"❌ Connection timeout for customer SSE ({session_id}): {e}"
                )
                yield f"event: error\ndata: Backend connection timeout\n\n".encode()
            except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                # Client disconnected - this is expected and normal, log at debug level
                logger.debug(
                    f"🔌 Client disconnected from customer SSE stream (session {session_id}): {type(e).__name__}"
                )
            except Exception as e:
                # Only log unexpected errors
                error_msg = str(e)
                if (
                    "peer closed connection" not in error_msg.lower()
                    and "incomplete chunked read" not in error_msg.lower()
                ):
                    logger.error(f"❌ Error in customer SSE stream: {e}")
                else:
                    logger.debug(
                        f"🔌 Client disconnection during customer SSE stream (session {session_id}): {e}"
                    )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        logger.error(f"❌ Error setting up customer SSE proxy: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# AGENT MESSAGE PROXY
# =================================


@router.post("/configuration/admin/chat-sessions/messages")
async def proxy_agent_message(request: Request):
    """Proxy agent messages - converts session UUID to numeric ID before forwarding"""
    try:
        logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Proxy endpoint called")
        logger.info(
            f"🔍 [AGENT_MESSAGE_PROXY] Request headers: {dict(request.headers)}"
        )

        settings = get_settings()
        config_service_url = settings.configuration_service_url  # Lowercase!

        # Get request body
        body = await request.json()
        logger.info(f"🔍 [AGENT_MESSAGE_PROXY] Request body: {body}")

        session_id = body.get("session_id")

        if not session_id:
            logger.error(f"❌ [AGENT_MESSAGE_PROXY] session_id missing in request body")
            raise HTTPException(status_code=400, detail="session_id is required")

        # PG18: session_id IS the UUIDv7 PK — no conversion needed
        logger.info(
            f"🔍 [AGENT_MESSAGE_PROXY] Received agent message for session: {session_id}"
        )

        # CRITICAL: Set agent_id from authenticated user (NOT from body)
        # Read from request.state (set by SessionAuthMiddleware after Firebase verification)
        # This ensures the actual sender's email is used for authorization
        user_email = getattr(request.state, "user_email", "")
        if user_email:
            body["agent_id"] = user_email
            logger.info(
                f"🔍 [AGENT_MESSAGE_PROXY] Set agent_id from authenticated user: {user_email}"
            )
        else:
            logger.warning(
                f"⚠️ [AGENT_MESSAGE_PROXY] No authenticated user email found in request state"
            )

        # Forward to configuration service with authenticated user info
        forward_headers = {
            "X-User-Email": user_email or "",
            "X-User-Role": getattr(request.state, "user_role", "") or "",
            "X-User-Role-ID": getattr(request.state, "user_role_id", "") or "",
            "X-Tenant-ID": getattr(request.state, "tenant_id", "") or "",
            "X-Tenant-Slug": getattr(request.state, "tenant_slug", "") or "",
            "Content-Type": "application/json",
        }
        _sign_internal_headers(
            forward_headers,
            method="POST",
            path_or_url=f"{config_service_url}/api/v1/configuration/admin/chat-sessions/messages",
        )
        async with AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config_service_url}/api/v1/configuration/admin/chat-sessions/messages",
                json=body,
                headers=forward_headers,
            )

            logger.info(
                f"✅ [AGENT_MESSAGE_PROXY] Forwarded message to configuration service, status: {response.status_code}"
            )

            if response.status_code != 200:
                logger.error(
                    f"❌ [AGENT_MESSAGE_PROXY] Configuration service returned error: {response.text}"
                )
                raise HTTPException(
                    status_code=response.status_code, detail=response.text
                )

            return response.json()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"❌ [AGENT_MESSAGE_PROXY] Error proxying agent message: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/auth/user/{uid}")
async def get_user_by_uid(uid: str):
    """Get user information by Firebase UID."""
    try:
        user_data = get_user_from_firebase(uid)
        if not user_data:
            raise HTTPException(status_code=404, detail=f"User not found: {uid}")
        return {"success": True, "user": user_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user by UID {uid}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")


@router.post("/auth/login")
async def login_user(request: Request):
    """Login user with Firebase token"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Missing or invalid authorization header"
            )

        token = auth_header.split(" ")[1]
        user_data = verify_firebase_token(token)

        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {"success": True, "user": user_data, "message": "Login successful"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during login: {e}")
        raise HTTPException(status_code=500, detail=f"Error during login: {str(e)}")


@router.post("/users/switch-role")
async def switch_user_role(request: Request):
    """Switch the user's role by removing old roles and adding new role (users can have only ONE active role)"""
    try:
        # Get uid from query parameter
        uid = request.query_params.get("uid")
        if not uid:
            raise HTTPException(status_code=400, detail="Missing uid parameter")

        # Get role from request body
        body = await request.json()
        new_role = body.get("role")
        if not new_role:
            raise HTTPException(status_code=400, detail="Missing role in request body")

        # Validate role is one of the allowed values
        valid_roles = ["admin", "agent", "customer"]  # Backend API expects these
        if new_role not in valid_roles:
            raise HTTPException(
                status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}"
            )

        logger.info(f"🔄 Switching user {uid} to role: {new_role}")

        try:
            # Import database session and text
            from sqlalchemy import text
            from shared.sqlalchemy_db import get_db_session

            user_id = uid

            async with get_db_session() as session:
                # Step 1: Get user's current roles
                get_roles_query = text("""
                    SELECT r.role_name, r.id as role_id
                    FROM user_role_mapping urm
                    JOIN roles r ON urm.role_id = r.id
                    WHERE urm.user_id = CAST(:user_id AS UUID)
                      AND urm.is_active = true
                      AND urm.tenant_id = current_tenant_id_optional()
                """)
                result = await session.execute(get_roles_query, {"user_id": user_id})
                current_roles = result.fetchall()

                if not current_roles:
                    logger.warning(f"⚠️ User {uid} has no current roles")
                    raise HTTPException(
                        status_code=404, detail="User has no current roles"
                    )

                logger.info(
                    f"📋 User {uid} current roles: {[r['role_name'] for r in current_roles]}"
                )

                # Step 2: Remove all current roles
                for current_role in current_roles:
                    remove_query = text("""
                        UPDATE user_role_mapping
                        SET is_active = false, updated_at = NOW()
                        WHERE user_id = CAST(:user_id AS UUID)
                          AND role_id = :role_id
                          AND tenant_id = current_tenant_id_optional()
                    """)
                    await session.execute(
                        remove_query,
                        {"user_id": user_id, "role_id": current_role["role_id"]},
                    )
                    logger.info(f"✂️ Removed role: {current_role['role_name']}")

                # Step 3: Get the ID of the new role
                get_new_role_id = text("""
                    SELECT id FROM roles WHERE role_name = :role_name
                """)
                result = await session.execute(get_new_role_id, {"role_name": new_role})
                new_role_row = result.fetchone()

                if not new_role_row:
                    logger.error(f"❌ Role '{new_role}' not found in database")
                    raise HTTPException(
                        status_code=400, detail=f"Role '{new_role}' not found"
                    )

                new_role_id = new_role_row["id"]

                # Step 4: Add new role
                add_query = text("""
                    INSERT INTO user_role_mapping (user_id, role_id, tenant_id, is_active, created_at, updated_at)
                    VALUES (CAST(:user_id AS UUID), :role_id, current_tenant_id_optional(), true, NOW(), NOW())
                    ON CONFLICT (user_id, role_id, tenant_id) DO UPDATE
                    SET is_active = true, updated_at = NOW()
                """)
                await session.execute(
                    add_query, {"user_id": user_id, "role_id": new_role_id}
                )
                logger.info(f"➕ Added new role: {new_role}")

                # Commit all changes
                await session.commit()

            logger.info(f"✅ Successfully switched user {uid} to role: {new_role}")

            return {
                "success": True,
                "message": f"Role switched to {new_role}",
                "uid": uid,
                "role": new_role,
            }

        except HTTPException:
            raise
        except Exception as db_error:
            logger.error(f"❌ Error updating database: {db_error}")
            raise HTTPException(
                status_code=500, detail=f"Error switching role: {str(db_error)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching user role: {e}")
        raise HTTPException(status_code=500, detail=f"Error switching role: {str(e)}")


# =================================
# PUBLIC CHAT ENDPOINTS (No Authentication Required)
# =================================


@router.post("/chatbot/chat/stream")
@limiter.limit("50/minute")
async def public_chat_stream(request: Request):
    """Chat streaming endpoint for both public widget traffic and authenticated dashboard traffic."""
    try:
        import httpx
        from ..core.config import get_settings

        is_authenticated_session = hasattr(
            request.state, "user"
        ) or _apply_authenticated_session_context(request)
        if not is_authenticated_session:
            _require_public_widget_context(
                request,
                expected_scopes=(WIDGET_SESSION_TOKEN_SCOPE,),
            )

        # Get request body - just pass it through as-is
        # Client should NOT send session_id (comes from cookie) or use_rag (defaults to true)
        body_bytes = await request.body()

        # ============================================================================
        # VALIDATION MOVED TO WINDOW-LOAD ENDPOINT (/chatbot/validate-chat)
        # ============================================================================
        # Chat availability and domain validation are now performed at widget
        # initialization time (window load) via the /chatbot/validate-chat endpoint.
        # This hot-path streaming endpoint assumes validation has already passed.
        #
        # REMOVED (moved to window-load):
        # - display_chatbot check: HTTP call to config service (500-1000ms latency)
        # - Domain validation: Not needed per-message (window-load is sufficient)
        #
        # BENEFIT: Reduces streaming response time by ~1 second (10-20x faster)
        # ============================================================================

        settings = get_settings()
        chatbot_service_url = settings.chatbot_orchestration_url

        # Correlation ID for end-to-end tracing across gateway -> chatbot service
        from shared.correlation_id import (
            get_correlation_id,
            add_correlation_id_headers,
            set_correlation_id,
        )
        from shared.otel_logger import set_request_id

        correlation_id = request.headers.get("X-Correlation-ID") or get_correlation_id()
        set_correlation_id(correlation_id)
        set_request_id(correlation_id)
        logger.info(f"🔍 [{correlation_id}] Public chat stream request received")

        # Prepare headers - remove auth-related headers for public endpoint
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("authorization", None)
        _remove_untrusted_identity_headers(headers)
        headers = add_correlation_id_headers(headers, correlation_id)
        _inject_identity_headers(request, headers)

        # Make request to chatbot service — streaming SSE proxy
        # No read timeout: first chunk can take a while (RAG search + AI inference)
        # Chunks are forwarded to the client as they arrive from the backend
        # IMPORTANT: httpx client + stream must live INSIDE the generator so the
        # connection stays open while FastAPI iterates chunks (same pattern as
        # the admin/customer SSE proxies at lines 151-158).
        sse_timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=None)
        stream_url = f"{chatbot_service_url}/api/v1/chatbot/chat/stream"
        _sign_internal_headers(headers, method=request.method, path_or_url=stream_url)

        from fastapi.responses import StreamingResponse

        async def stream_response():
            try:
                async with httpx.AsyncClient(
                    timeout=sse_timeout, follow_redirects=False
                ) as client:
                    async with client.stream(
                        method=request.method,
                        url=stream_url,
                        headers=headers,
                        content=body_bytes,
                    ) as response:
                        logger.info(
                            f"✅ [{correlation_id}] Chat stream connected: {response.status_code}"
                        )
                        async for chunk in response.aiter_bytes():
                            yield chunk
            except httpx.ConnectError as e:
                logger.error(
                    f"❌ [{correlation_id}] Cannot connect to chatbot service: {e}"
                )
                yield f'data: {{"type":"error","content":"Connection to backend failed"}}\n\n'.encode()
            except httpx.ConnectTimeout as e:
                logger.error(
                    f"❌ [{correlation_id}] Connection timeout to chatbot service: {e}"
                )
                yield f'data: {{"type":"error","content":"Backend connection timeout"}}\n\n'.encode()
            except (BrokenPipeError, ConnectionResetError, RuntimeError) as e:
                logger.debug(
                    f"🔌 [{correlation_id}] Client disconnected from chat stream: {type(e).__name__}"
                )
            except Exception as e:
                logger.error(f"❌ [{correlation_id}] Chat stream error: {e}")
                yield f'data: {{"type":"error","content":"Stream error"}}\n\n'.encode()

        return StreamingResponse(
            stream_response(),
            media_type="text/event-stream",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public chat stream: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# PROFILING PROXY ENDPOINTS (Admin only - auth required)
# =================================


@router.get("/chatbot/profiling/{path:path}")
async def proxy_profiling(request: Request, path: str):
    """Proxy profiling endpoints to chatbot orchestration service."""
    try:
        settings = get_settings()
        chatbot_service_url = settings.chatbot_orchestration_url
        target_url = f"{chatbot_service_url}/api/v1/chatbot/profiling/{path}"

        # Forward query params
        if request.query_params:
            target_url += f"?{request.query_params}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(target_url)
            content_type = resp.headers.get("content-type", "")
            # Pass through HTML/text responses as-is (for the dashboard)
            if "text/html" in content_type:
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type="text/html",
                )
            if "text/plain" in content_type:
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type="text/plain",
                )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        logger.error(f"Profiling proxy error: {e}")
        raise HTTPException(status_code=502, detail=f"Profiling proxy error: {str(e)}")


# =================================
# PUBLIC WIDGET CONFIGURATION ENDPOINT (No Authentication Required)
# =================================


@router.get("/configuration/widgetConfig")
async def get_widget_config(request: Request):
    """
    Proxy endpoint for widget configuration.
    Used by embedded bubble widget to load chat settings (colors, display name, etc).
    No authentication required - public endpoint - allows all origins.
    """
    try:
        _require_public_widget_context(
            request,
            expected_scopes=(WIDGET_SESSION_TOKEN_SCOPE,),
        )
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/widgetConfig"

        logger.info(f"🔄 Proxying widget config request to: {full_url}")
        forward_headers: Dict[str, str] = {}
        _inject_identity_headers(request, forward_headers)
        _sign_internal_headers(forward_headers, method="GET", path_or_url=full_url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url, headers=forward_headers or None)

            if response.status_code == 200:
                config_data = response.json()
                logger.info(
                    f"✓ Widget config loaded: display_name={config_data.get('display_name')}, has_icon={bool(config_data.get('chat_icon_url'))}"
                )
                logger.info(
                    f"📋 Suggested messages in response: {len(config_data.get('suggested_messages', []))}"
                )
                if config_data.get("suggested_messages"):
                    for i, msg in enumerate(
                        config_data.get("suggested_messages", []), 1
                    ):
                        logger.info(f"   [{i}] {msg}")
                # Explicitly set CORS headers for public endpoint
                return JSONResponse(
                    content=config_data,
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                    },
                )
            else:
                logger.error(
                    f"❌ Config service returned {response.status_code}: {response.text[:200]}"
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to load widget configuration",
                )

    except Exception as e:
        logger.error(f"❌ Error proxying widget config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error loading widget configuration: {str(e)}"
        )


# =================================
# ADMIN WIDGET CONFIGURATION ENDPOINT (Authentication Required)
# =================================


@router.get("/configuration/admin/widgetConfig")
async def get_admin_widget_config(request: Request):
    """
    Admin endpoint for widget configuration.
    Used by admin dashboard to manage chat settings.
    Requires authentication - allows credentials.
    """
    try:
        # User is already authenticated by SessionAuthMiddleware
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/widgetConfig"

        logger.info(f"🔄 Proxying admin widget config request to: {full_url}")
        forward_headers: Dict[str, str] = {}
        _inject_identity_headers(request, forward_headers)
        _sign_internal_headers(forward_headers, method="GET", path_or_url=full_url)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(full_url, headers=forward_headers or None)

            if response.status_code == 200:
                config_data = response.json()
                logger.info(
                    f"✓ Admin widget config loaded: display_name={config_data.get('display_name')}"
                )
                logger.info(
                    f"📋 Suggested messages in response: {len(config_data.get('suggested_messages', []))}"
                )
                if config_data.get("suggested_messages"):
                    for i, msg in enumerate(
                        config_data.get("suggested_messages", []), 1
                    ):
                        logger.info(f"   [{i}] {msg}")
                # Return with specific origin and credentials allowed
                origin = request.headers.get("origin", "*")
                return JSONResponse(
                    content=config_data,
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                        "Access-Control-Allow-Credentials": "true",
                    },
                )
            else:
                logger.error(
                    f"❌ Config service returned {response.status_code}: {response.text[:200]}"
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to load widget configuration",
                )

    except Exception as e:
        logger.error(f"❌ Error proxying admin widget config: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error loading widget configuration: {str(e)}"
        )


@router.post("/configuration/admin/widgetConfig")
async def save_admin_widget_config(request: Request):
    """
    Admin endpoint for saving widget configuration.
    Requires authentication - allows credentials.
    """
    try:
        # User is already authenticated by SessionAuthMiddleware
        settings = get_settings()
        config_service_url = settings.configuration_service_url
        full_url = f"{config_service_url}/api/v1/configuration/widgetConfig"

        # Get request body and forward original content-type (may be multipart/form-data with images)
        body = await request.body()
        content_type = request.headers.get("content-type", "application/json")

        logger.info(
            f"🔄 Proxying admin widget config save request to: {full_url} (content-type: {content_type[:50]})"
        )
        forward_headers: Dict[str, str] = {"Content-Type": content_type}
        _inject_identity_headers(request, forward_headers)
        _sign_internal_headers(forward_headers, method="POST", path_or_url=full_url)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                full_url, content=body, headers=forward_headers
            )

            if response.status_code in [200, 201]:
                config_data = response.json()
                logger.info(f"✓ Admin widget config saved")
                # Return with specific origin and credentials allowed
                origin = request.headers.get("origin", "*")
                return JSONResponse(
                    content=config_data,
                    status_code=response.status_code,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                        "Access-Control-Allow-Headers": "*",
                        "Access-Control-Allow-Credentials": "true",
                    },
                )
            else:
                logger.error(
                    f"❌ Config service returned {response.status_code}: {response.text[:200]}"
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to save widget configuration",
                )

    except Exception as e:
        logger.error(f"❌ Error proxying admin widget config save: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error saving widget configuration: {str(e)}"
        )


# =================================
# PUBLIC WIDGET ENDPOINT (No Authentication Required)
# =================================


@router.get("/widget")
async def public_widget(request: Request):
    """Public widget endpoint - serves HTML page with chat widget for iframe embedding"""
    try:
        _require_public_widget_context(request)

        # Get query parameters
        widget_mode = request.query_params.get("widgetMode", "true")
        theme = request.query_params.get("theme", "light")
        primary_color = request.query_params.get("primaryColor", "#3b82f6")
        display_name = request.query_params.get("displayName", "AI Assistant")
        widget_token = extract_widget_access_token(request)

        # Generate HTML page with embedded chat widget
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat Widget</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 100vh;
            overflow: hidden;
        }}
        .widget-container {{
            height: 100vh;
            width: 100vw;
        }}
    </style>
</head>
<body>
    <div id="widget-root" class="widget-container"></div>
    <script>
        // Widget configuration
        window.WIDGET_CONFIG = {{
            widgetMode: {widget_mode},
            theme: "{theme}",
            primaryColor: "{primary_color}",
            displayName: "{display_name}",
            widgetToken: "{widget_token}"
        }};
        
        // Load the chat widget
        (function() {{
            const script = document.createElement('script');
            script.src = '{request.base_url}/widget-script.js';
            script.async = true;
            script.onload = function() {{
                // Initialize widget if script provides initialization
                if (window.KnowledgeBot) {{
                    window.KnowledgeBot.init(window.WIDGET_CONFIG);
                }}
            }};
            document.head.appendChild(script);
        }})();
    </script>
</body>
</html>
        """

        from fastapi.responses import HTMLResponse

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"Error in public widget: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# GENERIC SERVICE PROXY HANDLER (catches ALL requests)
# =================================


@router.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
)
async def generic_proxy_handler(request: Request, path: str):
    """Generic proxy handler that routes ALL requests to appropriate services"""
    # Correlation ID for end-to-end tracing across gateway -> internal services.
    from shared.correlation_id import (
        get_correlation_id,
        set_correlation_id,
        add_correlation_id_headers,
    )
    from shared.otel_logger import set_request_id

    correlation_id = request.headers.get("X-Correlation-ID") or get_correlation_id()
    set_correlation_id(correlation_id)
    set_request_id(correlation_id)
    # Request/response are already logged by middleware; keep proxy handler logs minimal.
    logger.debug(f"[proxy] {request.method} {request.url.path}")

    try:
        import httpx
        from ..core.config import get_settings

        # Skip auth endpoints - handle them specifically
        if path.startswith("auth/"):
            return await handle_auth_endpoints(request, path)

        # Determine service based on URL path
        service_url = None

        logger.debug(f"[proxy] path='{path}'")

        # Remove /api/v1/ or api/v1/ prefix for routing logic (handle both with/without leading slash)
        if path.startswith("/api/v1/"):
            clean_path = path.replace("/api/v1/", "", 1)
        elif path.startswith("api/v1/"):
            clean_path = path.replace("api/v1/", "", 1)
        else:
            clean_path = path

        # Remove gateway/ prefix for backend service routing
        backend_path = (
            clean_path.replace("gateway/", "", 1)
            if clean_path.startswith("gateway/")
            else clean_path
        )

        # Determine service routing
        # Backend services register routers with /api/v1/{service_name} prefix
        service_path = backend_path  # Default: use backend_path as-is

        if backend_path.startswith("configuration/"):
            service_url = get_settings().configuration_service_url
            # Keep the service prefix - configuration service expects /api/v1/configuration/...
            logger.debug("Routing to configuration service")
        elif backend_path.startswith("chatbot/"):
            service_url = get_settings().chatbot_orchestration_url
            # Keep the service prefix - chatbot service expects /api/v1/chatbot/...
            logger.debug("Routing to chatbot service")
        elif backend_path.startswith("knowledgebase/"):
            service_url = get_settings().knowledgebase_ingestion_url
            # Keep the service prefix - knowledgebase service expects /api/v1/knowledgebase/...
            logger.debug("Routing to knowledgebase service")
        elif backend_path.startswith("webcrawl"):
            service_url = get_settings().knowledgebase_ingestion_url
            logger.debug("Routing webcrawl to knowledgebase_ingestion service")
        elif (
            backend_path.startswith("admin/")
            or backend_path.startswith("users/")
            or backend_path.startswith("widget/")
            or backend_path.startswith("feedback")
            or backend_path.startswith("messages/")
        ):
            # These are all configuration service endpoints but without the service prefix
            # Need to add "configuration/" prefix for proper routing
            service_url = get_settings().configuration_service_url
            service_path = f"configuration/{backend_path}"
            logger.debug("Routing to configuration service (non-prefixed endpoint)")
        else:
            logger.error(f"❌ Unknown path: {backend_path}")
            return JSONResponse(
                status_code=404, content={"error": f"Unknown path: {backend_path}"}
            )

        # Construct full URL for internal service communication
        # Internal services expect /api/v1/{service_name}/{endpoint}
        # The service_path already includes the service prefix (e.g., "configuration/users/profile")
        full_url = f"{service_url}/api/v1/{service_path}"
        upstream_url = _append_query_params(full_url, request.query_params)
        logger.debug(f"[proxy] upstream={service_url} url={upstream_url}")

        # Prepare headers
        headers = dict(request.headers)
        headers.pop("host", None)
        _remove_untrusted_identity_headers(headers)
        headers = add_correlation_id_headers(headers, correlation_id)
        _inject_identity_headers(request, headers)
        _sign_internal_headers(headers, method=request.method, path_or_url=upstream_url)

        # Forward session cookie to internal services for session validation
        settings = get_settings()
        session_cookie = request.cookies.get(settings.session_cookie_name)
        if session_cookie:
            headers["Cookie"] = f"{settings.session_cookie_name}={session_cookie}"
            logger.debug(f"🍪 Forwarding session cookie to internal service")

        # Make HTTP request to service
        # Use longer timeout for batch operations (file uploads/deletes) and complex queries
        # NOTE: webcrawl uses async Celery, returns immediately with task ID (no long timeout needed)
        request_timeout = 30.0
        if (
            "chatAgentConfig" in backend_path
            or "configuration/chatAgentConfig" in backend_path
        ):
            request_timeout = 60.0  # Configuration aggregates multiple DB queries
            logger.info(
                f"⏱️  Using extended timeout {request_timeout}s for chatAgentConfig (multiple parallel queries)"
            )
        elif (
            "batch" in backend_path
            or "batchupload" in backend_path
            or "delete/batch" in backend_path
        ):
            request_timeout = 300.0  # 5 minutes for batch operations
            logger.info(
                f"⏱️  Using extended timeout {request_timeout}s for batch operation"
            )
        # webcrawl/async returns immediately (task dispatched to Celery), no extended timeout needed
        # if backend_path.startswith("webcrawl"):
        #     request_timeout = 600.0  # Was for sync scraping - NO LONGER NEEDED
        #     logger.info(f"⏱️  Using extended timeout {request_timeout}s for web crawling")

        async with httpx.AsyncClient(
            timeout=request_timeout, follow_redirects=False
        ) as client:
            logger.info(
                f"🔍 About to make HTTP request to: {upstream_url} (timeout={request_timeout}s)"
            )

            # For SSE and other streaming responses, we need special handling
            # Check content-type to decide how to handle the response
            request_body = await request.body()

            # CRITICAL: Ensure numeric session_id in request body for internal services
            # API Gateway extracts UUID from cookie and converts to numeric ID
            # Internal services ONLY accept numeric session_id (never UUID)
            # EXCEPTION: set-current endpoints intentionally accept UUIDs
            should_ensure_session_id = (
                request_body
                and request.method in ["POST", "PUT", "PATCH"]
                and "set-current" not in full_url
            )

            if should_ensure_session_id:
                try:
                    import json

                    body_data = json.loads(request_body)

                    # Check if request has session_id
                    if "session_id" in body_data:
                        client_session_id = body_data["session_id"]

                        # PG18: session_id IS the UUIDv7 PK — pass through directly, no resolution needed
                        logger.debug(
                            f"PG18: Passing session_id through: {client_session_id}"
                        )
                    else:
                        # No session_id in body - try to inject from cookie if available
                        if (
                            hasattr(request.state, "session_id")
                            and request.state.session_id
                        ):
                            body_data["session_id"] = request.state.session_id
                            logger.info(
                                f"✅ Injected session_id from cookie into body: {request.state.session_id}"
                            )

                    request_body = json.dumps(body_data).encode()

                    # IMPORTANT: Update Content-Length header after modifying request body
                    # Remove old header first to avoid conflicting Content-Length headers
                    headers.pop("content-length", None)
                    headers["Content-Length"] = str(len(request_body))
                except HTTPException:
                    raise
                except (json.JSONDecodeError, ValueError) as e:
                    # Not JSON or other error - forward as-is
                    logger.debug(f"⚠️  Could not parse request body as JSON: {e}")
                    pass

            # Make request without streaming first to check headers
            response = await client.request(
                method=request.method,
                url=full_url,
                headers=headers,
                content=request_body,
                params=request.query_params,
            )
            logger.info(
                f"✅ Received response from {upstream_url} (Status: {response.status_code})"
            )

            # Create proper FastAPI Response from httpx response
            from fastapi.responses import StreamingResponse, Response

            # Check if response contains a session UUID that needs to be set in httpOnly cookie
            session_uuid_from_response = response.headers.get(
                "X-Session-UUID"
            ) or response.headers.get("x-session-uuid")

            # Copy headers from httpx response to FastAPI response
            # CRITICAL: Filter out headers that might contain internal URLs
            response_headers = {}
            blocked_headers = [
                "content-length",
                "transfer-encoding",
                "location",  # Prevent internal redirects from leaking
                "content-location",  # Prevent internal URLs in content location
                "host",  # Don't expose internal host
                "server",  # Don't expose server details
                "x-session-uuid",  # Remove internal header from response
            ]
            for key, value in response.headers.items():
                # Skip headers that might contain internal URLs or cause issues
                if key.lower() not in blocked_headers:
                    response_headers[key] = value

            # Create response
            response_obj = Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
            )

            # CRITICAL: Handle Set-Cookie headers separately (can have multiple)
            # httpx response.headers.get_list() returns all values for a header
            set_cookie_headers = response.headers.get_list("set-cookie")
            for cookie_header in set_cookie_headers:
                logger.info(
                    f"🍪 Forwarding Set-Cookie header from backend: {cookie_header[:50]}..."
                )
                response_obj.headers.append("set-cookie", cookie_header)

            # If response contains session UUID, set httpOnly cookie
            if session_uuid_from_response:
                logger.info(
                    f"🍪 Setting httpOnly cookie for session UUID: {session_uuid_from_response}"
                )
                response_obj.set_cookie(
                    key="chatbot_session_id",
                    value=session_uuid_from_response,
                    httponly=True,
                    secure=True,
                    samesite="Strict",
                    max_age=60 * 60 * 24,  # 24 hours
                )

            return response_obj
    except httpx.ConnectError as e:
        logger.error(f"❌ Connection failed to {full_url}: {e}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ This might mean the service is down or not accessible")
        logger.warning(
            f"⚠️  Attempting retry for service wake-up (Railway sleep/wake cycle)..."
        )

        # Retry logic for Railway services that might be sleeping
        retry_delays = [1.0, 2.0, 3.0]  # Exponential backoff for service wake-up
        for attempt, delay in enumerate(retry_delays, 1):
            try:
                logger.info(
                    f"🔄 Retry attempt {attempt}/{len(retry_delays)} after {delay}s delay..."
                )
                await asyncio.sleep(delay)

                async with httpx.AsyncClient(
                    timeout=request_timeout, follow_redirects=False
                ) as retry_client:
                    retry_response = await retry_client.request(
                        method=request.method,
                        url=full_url,
                        headers=headers,
                        content=body
                        if request.method in ["POST", "PUT", "PATCH"]
                        else None,
                        params=dict(request.query_params)
                        if request.query_params
                        else None,
                    )
                    logger.info(
                        f"✅ Retry successful! Status: {retry_response.status_code}"
                    )

                    # Handle streaming responses
                    if "text/event-stream" in retry_response.headers.get(
                        "content-type", ""
                    ):

                        async def retry_stream():
                            async with retry_response:
                                async for chunk in retry_response.aiter_bytes():
                                    yield chunk

                        return StreamingResponse(
                            retry_stream(), media_type="text/event-stream"
                        )

                    return Response(
                        content=retry_response.content,
                        status_code=retry_response.status_code,
                        headers=dict(retry_response.headers),
                    )
            except (httpx.ConnectError, httpx.TimeoutException) as retry_error:
                if attempt < len(retry_delays):
                    logger.warning(
                        f"⚠️  Retry {attempt} failed: {retry_error}, will retry again..."
                    )
                    continue
                else:
                    logger.error(
                        f"❌ All retry attempts failed. Service is not responding."
                    )
                    raise HTTPException(
                        status_code=503,
                        detail=f"Service unavailable after retries: {service_url}",
                    )

        raise HTTPException(
            status_code=503, detail=f"Service unavailable: {service_url}"
        )
    except httpx.TimeoutException as e:
        logger.error(f"❌ Request timeout to {full_url}: {e}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(
            f"❌ This could mean: service is slow, processing large files, or service is overloaded"
        )
        logger.warning(f"⚠️  Attempting retry for slow service wake-up...")

        # Retry logic for slow services (might be waking up)
        retry_delays = [2.0, 4.0, 6.0]  # Longer delays for timeout scenarios
        for attempt, delay in enumerate(retry_delays, 1):
            try:
                logger.info(
                    f"🔄 Timeout retry attempt {attempt}/{len(retry_delays)} after {delay}s delay..."
                )
                await asyncio.sleep(delay)

                async with httpx.AsyncClient(
                    timeout=request_timeout * 1.5, follow_redirects=False
                ) as retry_client:
                    retry_response = await retry_client.request(
                        method=request.method,
                        url=full_url,
                        headers=headers,
                        content=body
                        if request.method in ["POST", "PUT", "PATCH"]
                        else None,
                        params=dict(request.query_params)
                        if request.query_params
                        else None,
                    )
                    logger.info(
                        f"✅ Timeout retry successful! Status: {retry_response.status_code}"
                    )

                    # Handle streaming responses
                    if "text/event-stream" in retry_response.headers.get(
                        "content-type", ""
                    ):

                        async def retry_stream():
                            async with retry_response:
                                async for chunk in retry_response.aiter_bytes():
                                    yield chunk

                        return StreamingResponse(
                            retry_stream(), media_type="text/event-stream"
                        )

                    return Response(
                        content=retry_response.content,
                        status_code=retry_response.status_code,
                        headers=dict(retry_response.headers),
                    )
            except (httpx.ConnectError, httpx.TimeoutException) as retry_error:
                if attempt < len(retry_delays):
                    logger.warning(
                        f"⚠️  Timeout retry {attempt} failed: {retry_error}, will retry again..."
                    )
                    continue
                else:
                    logger.error(
                        f"❌ All timeout retry attempts failed. Service is not responding."
                    )
                    raise HTTPException(
                        status_code=504,
                        detail=f"Service timeout after retries: {service_url}",
                    )

        error_detail = f"Service timeout: {service_url}"
        if "batch" in backend_path:
            error_detail += " (batch operation took too long - check service logs)"
        raise HTTPException(status_code=504, detail=error_detail)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Proxy error for path '{path}': {error_msg}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        logger.error(f"❌ Full URL: {full_url}")
        logger.error(f"❌ Service URL: {service_url}")
        logger.error(f"❌ Full traceback: {type(e).__name__}: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Proxy error: {error_msg}")


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "api_gateway"}


# =================================
# AUTH ENDPOINTS (only these are specific)
# =================================


async def handle_auth_endpoints(request: Request, path: str):
    """Handle authentication endpoints specifically"""
    if path == "auth/verify" and request.method == "POST":
        # Get token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Missing or invalid authorization header"
            )

        token = auth_header.split(" ")[1]
        user_data = verify_firebase_token(token)

        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {"success": True, "user": user_data}
    elif path.startswith("auth/user/") and request.method == "GET":
        uid = path.split("/")[-1]
        try:
            user_data = get_user_from_firebase(uid)
            if not user_data:
                raise HTTPException(status_code=404, detail=f"User not found: {uid}")
            return {"success": True, "user": user_data}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting user by UID {uid}: {e}")
            raise HTTPException(status_code=500, detail=f"Error getting user: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail=f"Auth endpoint not found: {path}")


# =================================
# DEBUG ENDPOINTS
# =================================


@router.get("/debug/auth-headers")
async def debug_auth_headers(request: Request):
    """Debug endpoint to check what auth headers are being received"""
    return {
        "authorization_header": request.headers.get("authorization", "NOT PRESENT"),
        "x_user_uid": request.headers.get("x-user-uid", "NOT PRESENT"),
        "x_user_email": request.headers.get("x-user-email", "NOT PRESENT"),
        "x_user_name": request.headers.get("x-user-name", "NOT PRESENT"),
        "has_request_state_user": hasattr(request.state, "user"),
        "request_state_user": str(getattr(request.state, "user", "NOT PRESENT")),
        "all_headers": dict(request.headers),
    }


# =================================
# END OF ROUTER - Only generic proxy and auth handling
# =================================
