import re
from typing import List, Dict

try:
    import bleach
except ImportError:
    # Fallback if bleach is not available
    def clean(text, tags=[], attributes={}, strip=True):
        return text.strip() if strip else text
    bleach = type('bleach', (), {'clean': staticmethod(clean)})()

from ..schemas.models import ChatbotConfigRequest

def sanitize_text_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input to prevent XSS and other attacks"""
    if not text:
        return text

    # Configure allowed tags and attributes
    allowed_tags = []  # No HTML tags allowed for configuration text
    allowed_attributes = {}

    # Clean the text
    sanitized = bleach.clean(
        text,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=True
    )

    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized.strip()

def validate_configuration_consistency(config: ChatbotConfigRequest):
    """Validate that configuration settings are consistent with business rules"""
    errors = []

    # If HIL is enabled, ensure there are human agents
    if config.hil_enabled and (not config.human_agents or len(config.human_agents) == 0):
        errors.append("Human-in-the-Loop is enabled but no human agents are configured")

    # If HIL is disabled, warn about removing agents
    if config.hil_enabled is False and config.human_agents and len(config.human_agents) > 0:
        errors.append("Human-in-the-Loop is disabled but human agents are still configured")

    # Validate admin email domains (optional business rule)
    if config.admin_emails:
        allowed_domains = ['company.com', 'trusted-domain.org']  # Configure as needed
        for email in config.admin_emails:
            if isinstance(email, str):
                try:
                    domain = email.split('@')[1].lower()
                    if domain not in allowed_domains:
                        errors.append(f"Admin email domain '{domain}' is not in allowed domains")
                except IndexError:
                    pass

    return errors
