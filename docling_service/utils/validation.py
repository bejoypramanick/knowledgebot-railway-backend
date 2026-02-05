"""Input validation utilities for Docling Service."""
import os
from typing import Tuple

from docling_service.utils.constants import (
    SUPPORTED_FILE_TYPES,
    SKIP_DOCLING_TYPES,
    MAX_FILE_SIZE_BYTES
)


def validate_file_for_processing(
    filename: str,
    file_size: int
) -> Tuple[bool, str]:
    """
    Validate if a file should be processed by docling.

    Args:
        filename: Name of the file
        file_size: Size of the file in bytes

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Get file extension
    _, ext = os.path.splitext(filename.lower())

    # Check if file type should skip docling
    if ext in SKIP_DOCLING_TYPES:
        return False, f"File type {ext} should be uploaded as-is (already text/structured)"

    # Check if file type is supported
    if ext not in SUPPORTED_FILE_TYPES:
        return False, f"File type {ext} not supported by docling"

    # Check file size
    if file_size > MAX_FILE_SIZE_BYTES:
        size_mb = file_size / (1024 * 1024)
        max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return False, f"File size {size_mb:.1f}MB exceeds maximum {max_mb:.0f}MB"

    return True, ""


def should_use_docling(filename: str, mime_type: str, file_size: int) -> bool:
    """
    Quick check if docling should be used for this file.

    Args:
        filename: Original filename
        mime_type: Detected MIME type
        file_size: File size in bytes

    Returns:
        True if docling should be used, False otherwise
    """
    is_valid, _ = validate_file_for_processing(filename, file_size)
    return is_valid
