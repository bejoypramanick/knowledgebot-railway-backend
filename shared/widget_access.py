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
from typing import Any, Dict, Optional

from fastapi import Request


WIDGET_TOKEN_SCOPE = "public_widget"
WIDGET_TOKEN_QUERY_KEYS = ("widget_token", "widgetToken")
WIDGET_TOKEN_HEADER = "X-Widget-Access-Token"
DEFAULT_WIDGET_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 365 * 5


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


def issue_widget_access_token(
    tenant_id: str,
    tenant_slug: Optional[str] = None,
    expires_in_seconds: int = DEFAULT_WIDGET_TOKEN_TTL_SECONDS,
) -> str:
    now = int(time.time())
    payload = {
        "v": 1,
        "scope": WIDGET_TOKEN_SCOPE,
        "tenant_id": tenant_id,
        "tenant_slug": tenant_slug,
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _sign_token_payload(encoded_payload)
    return f"{encoded_payload}.{signature}"


def verify_widget_access_token(token: Optional[str]) -> Optional[Dict[str, Any]]:
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

    if payload.get("scope") != WIDGET_TOKEN_SCOPE:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        return None

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
