"""
Email Masking Utility
Masks email addresses to show only first letter and domain for display purposes
"""

def mask_email(email: str) -> str:
    """
    Mask an email address to show only first letter and domain.
    
    Examples:
        john.doe@example.com -> j***@example.com
        a@example.com -> a***@example.com
        admin@globistaan.com -> a***@globistaan.com
    
    Args:
        email: The email address to mask
        
    Returns:
        Masked email address
    """
    if not email or not isinstance(email, str):
        return email
    
    # Split email into local and domain parts
    if '@' not in email:
        return email
    
    local_part, domain_part = email.split('@', 1)
    
    if not local_part:
        return email
    
    # Keep first letter, mask the rest
    masked_local = local_part[0] + '***'
    
    return f"{masked_local}@{domain_part}"


def mask_emails_list(emails: list) -> list:
    """
    Mask a list of email addresses for display.
    
    Args:
        emails: List of email addresses
        
    Returns:
        List of masked email addresses
    """
    if not isinstance(emails, list):
        return emails
    
    return [mask_email(email) for email in emails]


def create_masked_email_map(emails: list) -> dict:
    """
    Create a mapping of masked emails to original emails.
    This allows the frontend to work with masked emails while preserving original data.
    
    Args:
        emails: List of original email addresses
        
    Returns:
        Dictionary mapping masked email -> original email
        
    Example:
        Input: ['john@example.com', 'jane@example.com']
        Output: {
            'j***@example.com': 'john@example.com',
            'j***@example.com': 'jane@example.com'  # Note: collision possible
        }
    """
    if not isinstance(emails, list):
        return {}
    
    email_map = {}
    for email in emails:
        if email:
            masked = mask_email(email)
            email_map[masked] = email
    
    return email_map
