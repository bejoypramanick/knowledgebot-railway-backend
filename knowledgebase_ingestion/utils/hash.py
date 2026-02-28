"""
Hash calculation utilities for duplicate detection.
"""

import hashlib


async def calculate_file_hash(file_bytes: bytes) -> str:
    """
    Calculate SHA256 hash of file content.

    Args:
        file_bytes: Binary content of the file

    Returns:
        SHA256 hash as hex string (64 characters)
    """
    return hashlib.sha256(file_bytes).hexdigest()
