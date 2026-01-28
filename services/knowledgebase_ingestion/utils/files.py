import hashlib
import os
import logging
import tempfile
from fastapi import UploadFile

logger = logging.getLogger(__name__)

def calculate_sha256(file_path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()

async def stream_to_temp_file(file: UploadFile, original_filename: str) -> tuple[str, int]:
    """Stream an uploaded file to a temporary location."""
    file_ext = os.path.splitext(original_filename)[1] or ".bin"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        tmp_path = tmp_file.name
        file_size = 0
        logger.info(f"💾 [STREAM] Starting stream of {original_filename} to {tmp_path}")
        
        while chunk := await file.read(1024 * 1024):
            tmp_file.write(chunk)
            file_size += len(chunk)
        
        logger.info(f"✅ [STREAM] Stream complete. Total size: {file_size} bytes")
        return tmp_path, file_size
