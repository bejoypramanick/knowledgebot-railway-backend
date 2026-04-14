import os
import re
from typing import Optional, Tuple

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
