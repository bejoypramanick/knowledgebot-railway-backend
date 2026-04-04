"""
Helpers for signing and verifying trusted internal service requests.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Mapping, MutableMapping, Optional
from urllib.parse import urlsplit

from fastapi import Request


INTERNAL_REQUEST_TIMESTAMP_HEADER = "X-Internal-Request-Timestamp"
INTERNAL_REQUEST_SIGNATURE_HEADER = "X-Internal-Request-Signature"
INTERNAL_REQUEST_CALLER_HEADER = "X-Internal-Request-Caller"
INTERNAL_REQUEST_MAX_AGE_SECONDS = 300


def _get_internal_request_secret() -> str:
    secret = os.getenv("INTERNAL_REQUEST_SECRET", "").strip()
    if not secret:
        raise RuntimeError("INTERNAL_REQUEST_SECRET is required for trusted internal requests")
    return secret


def _normalize_path(path_or_url: str) -> str:
    parsed = urlsplit(path_or_url)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def _signature_payload(method: str, path_or_url: str, timestamp: str, caller: str) -> bytes:
    normalized_path = _normalize_path(path_or_url)
    payload = "\n".join(
        [
            method.upper(),
            normalized_path,
            timestamp,
            caller or "",
        ]
    )
    return payload.encode("utf-8")


def _build_signature(method: str, path_or_url: str, timestamp: str, caller: str) -> str:
    secret = _get_internal_request_secret().encode("utf-8")
    payload = _signature_payload(method, path_or_url, timestamp, caller)
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def add_internal_request_signature(
    headers: MutableMapping[str, str],
    method: str,
    path_or_url: str,
    caller: str,
) -> MutableMapping[str, str]:
    timestamp = str(int(time.time()))
    headers[INTERNAL_REQUEST_TIMESTAMP_HEADER] = timestamp
    headers[INTERNAL_REQUEST_CALLER_HEADER] = caller
    headers[INTERNAL_REQUEST_SIGNATURE_HEADER] = _build_signature(
        method=method,
        path_or_url=path_or_url,
        timestamp=timestamp,
        caller=caller,
    )
    return headers


def has_identity_headers(headers: Mapping[str, str]) -> bool:
    identity_headers = (
        "X-User-UID",
        "X-User-Email",
        "X-User-Name",
        "X-User-Role",
        "X-User-Role-ID",
        "X-Tenant-ID",
        "X-Tenant-Slug",
    )
    return any(headers.get(header) for header in identity_headers)


def verify_internal_request(
    request: Request,
    max_age_seconds: int = INTERNAL_REQUEST_MAX_AGE_SECONDS,
) -> bool:
    timestamp = request.headers.get(INTERNAL_REQUEST_TIMESTAMP_HEADER)
    signature = request.headers.get(INTERNAL_REQUEST_SIGNATURE_HEADER)
    caller = request.headers.get(INTERNAL_REQUEST_CALLER_HEADER, "")

    if not timestamp or not signature:
        return False

    try:
        timestamp_value = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = int(time.time())
    if abs(now - timestamp_value) > max_age_seconds:
        return False

    try:
        expected_signature = _build_signature(
            method=request.method,
            path_or_url=str(request.url),
            timestamp=timestamp,
            caller=caller,
        )
    except RuntimeError:
        return False

    return hmac.compare_digest(signature, expected_signature)


def get_internal_request_caller(request: Request) -> Optional[str]:
    return request.headers.get(INTERNAL_REQUEST_CALLER_HEADER)
