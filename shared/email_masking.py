"""
Email Masking Utility
Masks email addresses for display purposes, preserving first 2 chars of local and domain parts.
"""


def mask_email(email: str) -> str:
    """
    Mask an email address for display.

    Examples:
        john.doe@example.com -> jo****@ex****.com
        ab@gmail.com -> ab****@gm****.com
        a@example.com -> a****@ex****.com
    """
    if not email or not isinstance(email, str):
        return email

    if '@' not in email:
        return email

    local, domain = email.rsplit('@', 1)
    domain_parts = domain.rsplit('.', 1)

    masked_local = local[:2] + '****' if len(local) > 2 else local[0] + '****'
    masked_domain = domain_parts[0][:2] + '****' if len(domain_parts[0]) > 2 else domain_parts[0]

    return f"{masked_local}@{masked_domain}.{domain_parts[-1]}"


def mask_emails_list(emails: list) -> list:
    """Mask a list of email addresses for display."""
    if not isinstance(emails, list):
        return emails
    return [mask_email(email) for email in emails]


def unmask_emails(submitted_emails: list, current_db_emails: list) -> list:
    """
    Replace masked emails with originals from DB, keep new unmasked emails as-is.

    For each submitted email:
    - If it contains '****' (masked), find the matching original by comparing masked versions
    - If it doesn't contain '****' (new email), keep it as-is
    """
    if not isinstance(submitted_emails, list):
        return submitted_emails

    result = []
    for email in submitted_emails:
        if '****' in str(email):
            # Find matching original by comparing masked versions
            for db_email in (current_db_emails or []):
                if mask_email(db_email) == email:
                    result.append(db_email)
                    break
        else:
            result.append(email)
    return result
