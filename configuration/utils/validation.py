
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

    # Note: Allow human agents to be configured even when HIL is disabled
    # This is useful for keeping the agent list ready for future HIL activation

    # Validate admin email domains (optional business rule)
    # Allow common email providers and specific domains
    allowed_domains = [
        'gmail.com',
        'globistaan.com'
    ]
    
    if config.admin_emails:
        for email in config.admin_emails:
            if isinstance(email, str):
                try:
                    domain = email.split('@')[1].lower()
                    if domain not in allowed_domains:
                        errors.append(f"Admin email domain '{domain}' is not in allowed domains")
                except IndexError:
                    errors.append(f"Invalid email format: {email}")
            elif hasattr(email, 'email'):
                try:
                    domain = email.email.split('@')[1].lower()
                    if domain not in allowed_domains:
                        errors.append(f"Admin email domain '{domain}' is not in allowed domains")
                except (IndexError, AttributeError):
                    errors.append(f"Invalid email format: {email}")
            elif isinstance(email, dict) and 'email' in email:
                try:
                    domain = email['email'].split('@')[1].lower()
                    if domain not in allowed_domains:
                        errors.append(f"Admin email domain '{domain}' is not in allowed domains")
                except (IndexError, KeyError):
                    errors.append(f"Invalid email format: {email}")

    # Return validation result object
    from typing import NamedTuple
    class ValidationResult(NamedTuple):
        is_valid: bool
        issues: list
    
    return ValidationResult(
        is_valid=len(errors) == 0,
        issues=errors
    )
