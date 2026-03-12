"""
Email Masking Utility
Masks email addresses to show only first letter and domain
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
    Mask a list of email addresses.
    
    Args:
        emails: List of email addresses
        
    Returns:
        List of masked email addresses
    """
    if not isinstance(emails, list):
        return emails
    
    return [mask_email(email) for email in emails]


def is_masked_email(email: str) -> bool:
    """
    Check if an email is masked (contains *** pattern).
    
    Args:
        email: The email address to check
        
    Returns:
        True if email is masked, False otherwise
    """
    if not email or not isinstance(email, str):
        return False
    
    return '***' in email


def filter_unmasked_emails(emails: list) -> list:
    """
    Filter out masked emails from a list, keeping only unmasked (new) emails.
    This is used when saving to prevent storing masked emails.
    
    Args:
        emails: List of email addresses (may contain masked and unmasked)
        
    Returns:
        List of only unmasked email addresses
    """
    if not isinstance(emails, list):
        return []
    
    return [email for email in emails if email and not is_masked_email(email)]
