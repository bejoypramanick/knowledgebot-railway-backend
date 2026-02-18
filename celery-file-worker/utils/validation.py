import os
import re
import puremagic
from typing import Optional, Tuple

from ..utils.constants import (ALLOWED_FILE_EXTENSIONS, ALLOWED_MIME_TYPES,
                               MAX_FILE_SIZE_BYTES)


def validate_file_extension(filename: str) -> Tuple[bool, str]:
    """Validate file extension is allowed."""
    if not filename:
        return False, "Filename is required"
    
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if not ext:
        return False, "File must have an extension"
    
    if ext not in ALLOWED_FILE_EXTENSIONS:
        allowed_list = ', '.join(sorted(ALLOWED_FILE_EXTENSIONS))
        return False, f"File type '.{ext}' is not allowed. Allowed types: {allowed_list}"
    
    return True, ""

def validate_file_size(size_bytes: int) -> Tuple[bool, str]:
    """Validate file size is within limits."""
    if size_bytes <= 0:
        return False, "File is empty"

    if size_bytes > MAX_FILE_SIZE_BYTES:
        file_mb = size_bytes / (1024 * 1024)
        max_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        return False, f"File size ({file_mb:.2f} MB) exceeds maximum allowed size of {max_mb:.0f} MB"

    return True, ""

def validate_mime_type(mime_type: str, filename: str) -> Tuple[bool, str]:
    """Validate MIME type is allowed."""
    if not mime_type:
        return True, ""  # Allow missing mime type, will be detected
    
    # Be lenient - if extension is valid, accept even if mime type is generic
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ALLOWED_FILE_EXTENSIONS:
        return True, ""
    
    if mime_type not in ALLOWED_MIME_TYPES:
        return False, f"MIME type '{mime_type}' is not allowed"
    
    return True, ""

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and special characters."""
    filename = os.path.basename(filename)
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    return filename

from shared.file_utils import detect_mime_type as detect_mime_type_from_shared

def detect_mime_type_robust(file_path: str) -> str:
    """Delegate robust MIME detection to shared utility."""
    from shared.file_utils import detect_mime_type_robust as shared_detect
    return shared_detect(file_path)

def detect_mime_type_from_extension(filename: str, provided_mime_type: Optional[str] = None, file_path: Optional[str] = None) -> str:
    """Delegate MIME detection to shared utility."""
    return detect_mime_type_from_shared(filename, provided_mime_type, file_path)
