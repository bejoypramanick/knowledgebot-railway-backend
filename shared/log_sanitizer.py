"""
Log sanitization helpers.

Goal: prevent PII/secrets from reaching production logs while still keeping
stable identifiers for correlation/debugging.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Iterable, Optional


_DEFAULT_HASH_PREFIX_LEN = 10


def hash_pii(value: Optional[str], prefix_len: int = _DEFAULT_HASH_PREFIX_LEN) -> str:
    """Return a stable, non-reversible short hash for PII-like values."""
    if not value:
        return "none"
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()
    return digest[: max(4, int(prefix_len))]


def redact_headers(headers: Dict[str, Any], denylist: Iterable[str] = ()) -> Dict[str, Any]:
    """Return a copy of headers with sensitive fields removed."""
    deny = {h.lower() for h in denylist}
    deny |= {"authorization", "cookie", "x-api-key", "x-forwarded-authorization"}
    out: Dict[str, Any] = {}
    for k, v in (headers or {}).items():
        if str(k).lower() in deny:
            continue
        out[str(k)] = v
    return out

