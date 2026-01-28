from urllib.parse import urlparse
from typing import Optional, List, Tuple

MAX_URL_LENGTH = 2048
BLOCKED_DOMAINS = [
    'localhost', '127.0.0.1', '0.0.0.0',
    '192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.',
    '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
    '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.',
]
ALLOWED_SCHEMES = ['http', 'https']

def validate_url(url: str) -> Tuple[bool, str]:
    """Validate URL format and security."""
    if not url:
        return False, "URL is required"
    
    if len(url) > MAX_URL_LENGTH:
        return False, f"URL exceeds maximum length of {MAX_URL_LENGTH} characters"
    
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"
    
    if parsed.scheme not in ALLOWED_SCHEMES:
        return False, f"URL scheme must be one of: {', '.join(ALLOWED_SCHEMES)}"
    
    if not parsed.netloc:
        return False, "URL must include a domain (e.g., example.com)"
    
    host = parsed.netloc.lower()
    for blocked in BLOCKED_DOMAINS:
        if blocked in host:
            return False, f"Access to internal/local domains is not allowed"
    
    return True, ""

def validate_patterns(patterns: Optional[List[str]]) -> Tuple[bool, str]:
    """Validate include/exclude patterns."""
    if not patterns:
        return True, ""

    if len(patterns) > 50:
        return False, "Maximum 50 patterns allowed"

    for pattern in patterns:
        if len(pattern) > 500:
            return False, f"Pattern too long (max 500 chars): {pattern[:50]}..."
        dangerous = ['(?!', '(?=', '(?<', '(?P']
        for d in dangerous:
            if d in pattern:
                return False, f"Pattern contains potentially dangerous regex: {pattern[:50]}..."

    return True, ""
