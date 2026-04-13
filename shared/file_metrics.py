"""
File Metrics Utility
Calculates file size and character count for markdown content
"""
import os
from typing import Dict, Any, Tuple

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_metrics", "shared")


def calculate_metrics(content: str) -> Dict[str, int]:
    """
    Calculate file metrics for markdown content.

    Args:
        content: The markdown content as string

    Returns:
        Dictionary with 'char_count' and 'file_size_bytes'
    """
    try:
        # Character count: number of characters in content
        char_count = len(content)

        # Word count: simple whitespace split
        word_count = len(content.split())

        # File size: number of bytes when encoded as UTF-8
        file_size_bytes = len(content.encode('utf-8'))

        logger.info(f"📊 [METRICS] Content metrics calculated:")
        logger.info(f"   - Characters: {char_count:,}")
        logger.info(f"   - Words: {word_count:,}")
        logger.info(f"   - File size: {file_size_bytes:,} bytes ({file_size_bytes / 1024:.2f} KB)")

        return {
            "char_count": char_count,
            "word_count": word_count,
            "file_size_bytes": file_size_bytes
        }
    except Exception as e:
        logger.error(f"❌ Error calculating metrics: {e}")
        return {
            "char_count": 0,
            "file_size_bytes": 0
        }


def calculate_metrics_from_file(file_path: str) -> Dict[str, int]:
    """
    Calculate file metrics from a file on disk.

    Args:
        file_path: Path to the file

    Returns:
        Dictionary with 'char_count' and 'file_size_bytes'
    """
    try:
        if not os.path.exists(file_path):
            logger.error(f"❌ File not found: {file_path}")
            return {
                "char_count": 0,
                "file_size_bytes": 0
            }

        # Read file content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Calculate metrics
        return calculate_metrics(content)
    except Exception as e:
        logger.error(f"❌ Error calculating metrics from file: {e}")
        return {
            "char_count": 0,
            "file_size_bytes": 0
        }


def format_file_size(bytes_size: int) -> str:
    """
    Format file size in human-readable format.

    Args:
        bytes_size: Size in bytes

    Returns:
        Formatted size string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.2f} TB"
