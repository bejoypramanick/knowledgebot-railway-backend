"""File utilities for common operations like MIME detection."""
import os
import mimetypes
from typing import Optional

try:
    import puremagic
except ImportError:
    puremagic = None

def detect_mime_type_robust(file_path: str) -> str:
    """Robustly detect MIME type using magic bytes."""
    if puremagic is None:
        # Fallback to mimetypes if puremagic is not available
        guessed_type, _ = mimetypes.guess_type(file_path)
        return guessed_type or "application/octet-stream"
        
    try:
        exts = puremagic.from_file(file_path)
        if exts:
            return exts[0].mime_type
    except Exception:
        pass
    
    # Final fallback
    guessed_type, _ = mimetypes.guess_type(file_path)
    return guessed_type or "application/octet-stream"

def detect_mime_type(filename: str, provided_mime_type: Optional[str] = None, file_path: Optional[str] = None) -> str:
    """
    Detect proper MIME type from file extension and/or magic bytes.
    
    Args:
        filename: Original filename
        provided_mime_type: MIME type from request
        file_path: Optional path to the local file for magic byte detection
        
    Returns:
        The detected MIME type string
    """
    # Priority 1: Magic bytes if file_path is provided
    if file_path and os.path.exists(file_path):
        magic_mime = detect_mime_type_robust(file_path)
        if magic_mime and magic_mime != "application/octet-stream":
            return magic_mime

    # Priority 2: Provided MIME type if it's specific
    if provided_mime_type and provided_mime_type != "application/octet-stream":
        return provided_mime_type
    
    extension_to_mime = {
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'txt': 'text/plain',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'csv': 'text/csv',
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        'py': 'text/x-python',
        'js': 'application/javascript',
        'html': 'text/html',
        'htm': 'text/html',
        'json': 'application/json',
        'md': 'text/markdown',
    }
    
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    
    if ext in extension_to_mime:
        return extension_to_mime[ext]
    
    guessed_type, _ = mimetypes.guess_type(filename)
    if guessed_type:
        return guessed_type
    
    return provided_mime_type or "application/octet-stream"
