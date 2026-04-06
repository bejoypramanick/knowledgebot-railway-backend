"""
Signed widget access tokens for public tenant-scoped widget traffic.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from fastapi import Request


LEGACY_WIDGET_TOKEN_SCOPE = "public_widget"
WIDGET_EMBED_TOKEN_SCOPE = "public_widget_embed"
WIDGET_SESSION_TOKEN_SCOPE = "public_widget_session"
WIDGET_TOKEN_QUERY_KEYS = ("widget_token", "widgetToken")
WIDGET_TOKEN_HEADER = "X-Widget-Access-Token"
WIDGET_PARENT_ORIGIN_HEADER = "X-Widget-Parent-Origin"
DEFAULT_WIDGET_EMBED_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 365
DEFAULT_WIDGET_SESSION_TOKEN_TTL_SECONDS = 60 * 30


def _get_widget_token_secret() -> str:
    secret = os.getenv("WIDGET_TOKEN_SECRET", "").strip() or os.getenv("INTERNAL_REQUEST_SECRET", "").strip()
    if not secret:
        raise RuntimeError("WIDGET_TOKEN_SECRET or INTERNAL_REQUEST_SECRET is required for widget access tokens")
    return secret


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign_token_payload(encoded_payload: str) -> str:
    secret = _get_widget_token_secret().encode("utf-8")
    return hmac.new(secret, encoded_payload.encode("utf-8"), hashlib.sha256).hexdigest()


def normalize_widget_origin(origin: Optional[str]) -> Optional[str]:
    if not origin or not isinstance(origin, str):
        return None

    value = origin.strip()
    if not value:
        return None

    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
            return None
        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            return None
        port = parsed.port
    except ValueError:
        return None

    scheme = parsed.scheme.lower()
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or
        (scheme == "https" and port == 443)
    )
    port_suffix = f":{port}" if include_port else ""
    return f"{scheme}://{hostname}{port_suffix}"


def normalize_widget_allowed_origins(origins: Any) -> List[str]:
    if origins is None:
        return []

    if isinstance(origins, str):
        raw_items = [item.strip() for item in origins.replace("\r", "\n").replace(",", "\n").split("\n")]
    elif isinstance(origins, (list, tuple, set)):
        raw_items = list(origins)
    else:
        raise ValueError("allowed_origins must be a list of fully-qualified origins")

    normalized_items: List[str] = []
    seen = set()
    for item in raw_items:
        if item in (None, ""):
            continue
        normalized = normalize_widget_origin(str(item))
        if not normalized:
            raise ValueError(f"Invalid widget origin: {item}")
        if normalized not in seen:
            normalized_items.append(normalized)
            seen.add(normalized)

    return normalized_items


def extract_widget_parent_origin(request: Request) -> Optional[str]:
    return normalize_widget_origin(request.headers.get(WIDGET_PARENT_ORIGIN_HEADER))


def is_widget_origin_allowed(parent_origin: Optional[str], allowed_origins: Iterable[str]) -> bool:
    normalized_parent_origin = normalize_widget_origin(parent_origin)
    if not normalized_parent_origin:
        return False

    normalized_allowed_origins = {
        normalized
        for normalized in (normalize_widget_origin(origin) for origin in allowed_origins)
        if normalized
    }
    return normalized_parent_origin in normalized_allowed_origins


def issue_widget_access_token(
    tenant_id: str,
    tenant_slug: Optional[str] = None,
    expires_in_seconds: int = DEFAULT_WIDGET_EMBED_TOKEN_TTL_SECONDS,
) -> str:
    now = int(time.time())
    payload = {
        "v": 2,
        "scope": WIDGET_EMBED_TOKEN_SCOPE,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _sign_token_payload(encoded_payload)
    return f"{encoded_payload}.{signature}"


def issue_widget_session_token(
    tenant_id: str,
    tenant_slug: Optional[str] = None,
    parent_origin: Optional[str] = None,
    expires_in_seconds: int = DEFAULT_WIDGET_SESSION_TOKEN_TTL_SECONDS,
) -> str:
    normalized_parent_origin = normalize_widget_origin(parent_origin)
    if not normalized_parent_origin:
        raise ValueError("A valid parent origin is required for widget session tokens")

    now = int(time.time())
    payload = {
        "v": 2,
        "scope": WIDGET_SESSION_TOKEN_SCOPE,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "parent_origin": normalized_parent_origin,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _sign_token_payload(encoded_payload)
    return f"{encoded_payload}.{signature}"


def verify_widget_access_token(
    token: Optional[str],
    expected_scopes: Optional[Iterable[str]] = None,
) -> Optional[Dict[str, Any]]:
    if not token or "." not in token:
        return None

    encoded_payload, provided_signature = token.split(".", 1)
    try:
        expected_signature = _sign_token_payload(encoded_payload)
    except RuntimeError:
        return None

    if not hmac.compare_digest(provided_signature, expected_signature):
        return None

    try:
        payload = json.loads(_b64url_decode(encoded_payload).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    scope = payload.get("scope")
    allowed_scopes = set(expected_scopes or (
        LEGACY_WIDGET_TOKEN_SCOPE,
        WIDGET_EMBED_TOKEN_SCOPE,
        WIDGET_SESSION_TOKEN_SCOPE,
    ))
    if scope not in allowed_scopes:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        return None

    if scope == WIDGET_SESSION_TOKEN_SCOPE:
        parent_origin = normalize_widget_origin(payload.get("parent_origin"))
        if not parent_origin:
            return None
        payload["parent_origin"] = parent_origin

    return payload


def extract_widget_access_token(request: Request) -> Optional[str]:
    header_token = request.headers.get(WIDGET_TOKEN_HEADER)
    if header_token:
        return header_token

    for key in WIDGET_TOKEN_QUERY_KEYS:
        token = request.query_params.get(key)
        if token:
            return token

    return None
