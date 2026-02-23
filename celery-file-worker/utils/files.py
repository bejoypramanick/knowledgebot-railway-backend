import hashlib
import os

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("files_util", "celery-file-worker")

def calculate_sha256(file_path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()
