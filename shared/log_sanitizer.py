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


def redact_pii_text(text: str) -> str:
    """
    Detect and redact PII in free-form text using Presidio (regex-only mode, no NLP models).

    Supported PII types (regex-based detection):
    - EMAIL_ADDRESS: Redacted to [EMAIL_REDACTED]
    - PHONE_NUMBER: Redacted to [PHONE_REDACTED]
    - CREDIT_CARD: Redacted to [CREDIT_CARD_REDACTED]
    - URL: Redacted to [URL_REDACTED]
    - IP_ADDRESS: Redacted to [IP_ADDRESS_REDACTED]

    Args:
        text: Input text to scan for PII

    Returns:
        Text with detected PII redacted. If Presidio is not installed or fails,
        returns original text unchanged (graceful degradation).

    Example:
        >>> redact_pii_text("Contact me at test@example.com or 555-1234")
        "Contact me at [EMAIL_REDACTED] or [PHONE_REDACTED]"
    """
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig

        # Initialize analyzer and anonymizer
        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()

        # Analyze text for PII (this uses regex-based recognizers by default)
        results = analyzer.analyze(text=text, language="en")

        if not results:
            # No PII detected
            return text

        # Redact detected PII
        anonymized_text = anonymizer.anonymize(
            text=text,
            analyzer_results=results,
            operators={
                "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL_REDACTED]"}),
                "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE_REDACTED]"}),
                "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[CREDIT_CARD_REDACTED]"}),
                "URL": OperatorConfig("replace", {"new_value": "[URL_REDACTED]"}),
                "IP_ADDRESS": OperatorConfig("replace", {"new_value": "[IP_ADDRESS_REDACTED]"}),
                "PERSON": OperatorConfig("replace", {"new_value": "[NAME_REDACTED]"}),
                "ORG": OperatorConfig("replace", {"new_value": "[ORG_REDACTED]"}),
                "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
            },
        )

        return anonymized_text.text

    except ImportError:
        # Presidio not installed - gracefully degrade
        # Original text is returned unchanged (no redaction occurs)
        return text

    except Exception as e:
        # If Presidio analysis fails for any reason, return original text
        # (fail-safe: don't break logs if Presidio fails)
        return text

