"""
Upload Constraints Service
Manages file upload constraints (max file size, allowed types, etc.)
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import os

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("upload_constraints_service", "knowledgebase-ingestion")


@dataclass
class FileTypeConstraint:
    """Represents a file type constraint."""
    extension: str
    mime_types: List[str]
    category: str  # 'document', 'spreadsheet', 'presentation', 'code', 'archive', 'web'
    description: str


class UploadConstraintsService:
    """Service for managing file upload constraints."""

    # Supported file types with their MIME types and metadata
    SUPPORTED_FILE_TYPES = {
        # Documents
        "pdf": FileTypeConstraint(
            extension="pdf",
            mime_types=["application/pdf"],
            category="document",
            description="PDF Document"
        ),
        "docx": FileTypeConstraint(
            extension="docx",
            mime_types=[
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.template"
            ],
            category="document",
            description="Microsoft Word Document"
        ),
        "doc": FileTypeConstraint(
            extension="doc",
            mime_types=["application/msword"],
            category="document",
            description="Microsoft Word 97-2003 Document"
        ),
        "txt": FileTypeConstraint(
            extension="txt",
            mime_types=["text/plain"],
            category="document",
            description="Plain Text"
        ),
        "rtf": FileTypeConstraint(
            extension="rtf",
            mime_types=["application/rtf", "text/rtf"],
            category="document",
            description="Rich Text Format"
        ),

        # Spreadsheets
        "xlsx": FileTypeConstraint(
            extension="xlsx",
            mime_types=[
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.template"
            ],
            category="spreadsheet",
            description="Microsoft Excel Spreadsheet"
        ),
        "xls": FileTypeConstraint(
            extension="xls",
            mime_types=["application/vnd.ms-excel"],
            category="spreadsheet",
            description="Microsoft Excel 97-2003 Spreadsheet"
        ),
        "csv": FileTypeConstraint(
            extension="csv",
            mime_types=["text/csv"],
            category="spreadsheet",
            description="Comma-Separated Values"
        ),
        "tsv": FileTypeConstraint(
            extension="tsv",
            mime_types=["text/tab-separated-values"],
            category="spreadsheet",
            description="Tab-Separated Values"
        ),

        # Presentations
        "pptx": FileTypeConstraint(
            extension="pptx",
            mime_types=[
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.openxmlformats-officedocument.presentationml.template"
            ],
            category="presentation",
            description="Microsoft PowerPoint Presentation"
        ),
        "ppt": FileTypeConstraint(
            extension="ppt",
            mime_types=["application/vnd.ms-powerpoint"],
            category="presentation",
            description="Microsoft PowerPoint 97-2003 Presentation"
        ),

        # Code/Web
        "py": FileTypeConstraint(
            extension="py",
            mime_types=["text/x-python", "text/plain"],
            category="code",
            description="Python Code"
        ),
        "js": FileTypeConstraint(
            extension="js",
            mime_types=["application/javascript", "text/javascript", "text/plain"],
            category="code",
            description="JavaScript Code"
        ),
        "ts": FileTypeConstraint(
            extension="ts",
            mime_types=["text/typescript", "text/plain"],
            category="code",
            description="TypeScript Code"
        ),
        "html": FileTypeConstraint(
            extension="html",
            mime_types=["text/html"],
            category="web",
            description="HTML Document"
        ),
        "htm": FileTypeConstraint(
            extension="htm",
            mime_types=["text/html"],
            category="web",
            description="HTML Document"
        ),
        "xml": FileTypeConstraint(
            extension="xml",
            mime_types=["application/xml", "text/xml"],
            category="web",
            description="XML Document"
        ),
        "json": FileTypeConstraint(
            extension="json",
            mime_types=["application/json", "text/plain"],
            category="code",
            description="JSON Data"
        ),
        "md": FileTypeConstraint(
            extension="md",
            mime_types=["text/markdown", "text/plain"],
            category="document",
            description="Markdown Document"
        ),
        "yaml": FileTypeConstraint(
            extension="yaml",
            mime_types=["application/yaml", "application/x-yaml", "text/yaml", "text/plain"],
            category="code",
            description="YAML Configuration"
        ),
        "yml": FileTypeConstraint(
            extension="yml",
            mime_types=["application/yaml", "application/x-yaml", "text/yaml", "text/plain"],
            category="code",
            description="YAML Configuration"
        ),

        # Archives
        "zip": FileTypeConstraint(
            extension="zip",
            mime_types=["application/zip", "application/x-zip-compressed"],
            category="archive",
            description="ZIP Archive"
        ),
        "tar": FileTypeConstraint(
            extension="tar",
            mime_types=["application/x-tar"],
            category="archive",
            description="TAR Archive"
        ),
        "gz": FileTypeConstraint(
            extension="gz",
            mime_types=["application/gzip", "application/x-gzip"],
            category="archive",
            description="GZIP Compressed File"
        ),
        "tar.gz": FileTypeConstraint(
            extension="tar.gz",
            mime_types=["application/gzip", "application/x-gzip"],
            category="archive",
            description="Tar GZip Archive"
        ),

        # Images
        "png": FileTypeConstraint(
            extension="png",
            mime_types=["image/png"],
            category="image",
            description="PNG Image"
        ),
        "jpg": FileTypeConstraint(
            extension="jpg",
            mime_types=["image/jpeg"],
            category="image",
            description="JPEG Image"
        ),
        "jpeg": FileTypeConstraint(
            extension="jpeg",
            mime_types=["image/jpeg"],
            category="image",
            description="JPEG Image"
        ),
        "webp": FileTypeConstraint(
            extension="webp",
            mime_types=["image/webp"],
            category="image",
            description="WebP Image"
        ),
        "gif": FileTypeConstraint(
            extension="gif",
            mime_types=["image/gif"],
            category="image",
            description="GIF Image"
        ),
        "bmp": FileTypeConstraint(
            extension="bmp",
            mime_types=["image/bmp", "image/x-ms-bmp"],
            category="image",
            description="Bitmap Image"
        ),
        "tif": FileTypeConstraint(
            extension="tif",
            mime_types=["image/tiff"],
            category="image",
            description="TIFF Image"
        ),
        "tiff": FileTypeConstraint(
            extension="tiff",
            mime_types=["image/tiff"],
            category="image",
            description="TIFF Image"
        ),
        "svg": FileTypeConstraint(
            extension="svg",
            mime_types=["image/svg+xml"],
            category="image",
            description="SVG Image"
        ),
    }

    def __init__(self):
        """Initialize upload constraints service."""
        self._load_constraints_from_env()
        self._cache = None
        logger.info("✅ [INIT] UploadConstraintsService initialized")

    def _load_constraints_from_env(self):
        """Load upload constraints from environment variables."""
        # Max file size in MB from env, default to 100MB
        max_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
        self.max_file_size_bytes = max_size_mb * 1024 * 1024

        # Allowed extensions from env (comma-separated)
        allowed_exts_env = os.getenv("ALLOWED_FILE_EXTENSIONS", "")
        if allowed_exts_env:
            self.allowed_extensions = [ext.strip().lower() for ext in allowed_exts_env.split(",")]
            logger.info(f"🔧 [CONFIG] Loaded allowed extensions from env: {self.allowed_extensions}")
        else:
            # Default to all supported extensions
            self.allowed_extensions = list(self.SUPPORTED_FILE_TYPES.keys())

        logger.info(f"🔧 [CONFIG] Max file size: {max_size_mb}MB ({self.max_file_size_bytes} bytes)")

    def get_constraints(self) -> Dict[str, Any]:
        """
        Get file upload constraints.

        Returns:
            Dictionary with max_file_size, allowed_extensions, allowed_mime_types, etc.
        """
        logger.info("📋 [CONSTRAINTS] Generating upload constraints")

        # Build MIME types list from allowed extensions
        allowed_mime_types = []
        extensions_metadata = []

        for ext in self.allowed_extensions:
            ext_lower = ext.lower()
            if ext_lower in self.SUPPORTED_FILE_TYPES:
                constraint = self.SUPPORTED_FILE_TYPES[ext_lower]
                allowed_mime_types.extend(constraint.mime_types)
                extensions_metadata.append({
                    "extension": constraint.extension,
                    "category": constraint.category,
                    "description": constraint.description,
                    "mime_types": constraint.mime_types
                })
            else:
                logger.warning(f"⚠️  [CONSTRAINTS] Unknown extension: {ext}")

        constraints = {
            "success": True,
            "constraints": {
                "max_file_size": self.max_file_size_bytes,
                "max_file_size_display": f"{self.max_file_size_bytes // (1024 * 1024)} MB",
                "max_file_size_mb": self.max_file_size_bytes // (1024 * 1024),
                "allowed_extensions": self.allowed_extensions,
                "allowed_mime_types": list(set(allowed_mime_types)),  # Remove duplicates
                "supported_file_types": extensions_metadata,
                "file_categories": self._get_categories_summary()
            }
        }

        logger.info(f"✅ [CONSTRAINTS] Generated constraints with {len(self.allowed_extensions)} extension(s)")
        logger.info(f"   Max file size: {constraints['constraints']['max_file_size_display']}")
        logger.info(f"   Allowed extensions: {', '.join(self.allowed_extensions)}")
        logger.info(f"   MIME types: {len(constraints['constraints']['allowed_mime_types'])}")

        return constraints

    def _get_categories_summary(self) -> Dict[str, List[str]]:
        """Get summary of file types by category."""
        categories = {}

        for ext in self.allowed_extensions:
            ext_lower = ext.lower()
            if ext_lower in self.SUPPORTED_FILE_TYPES:
                constraint = self.SUPPORTED_FILE_TYPES[ext_lower]
                if constraint.category not in categories:
                    categories[constraint.category] = []
                categories[constraint.category].append({
                    "extension": ext,
                    "description": constraint.description
                })

        return categories

    def validate_file_extension(self, filename: str) -> tuple[bool, Optional[str]]:
        """
        Validate if a file extension is allowed.

        Args:
            filename: The filename to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not filename:
            return False, "Filename is required"

        # Get extension
        parts = filename.lower().split(".")
        if len(parts) < 2:
            return False, "Filename must have an extension"

        ext = parts[-1]

        # Check for double extension like .tar.gz
        if len(parts) > 2 and ext == "gz" and parts[-2] == "tar":
            ext = "tar.gz"

        if ext not in self.allowed_extensions:
            allowed_str = ", ".join(self.allowed_extensions)
            return False, f"File extension '.{ext}' not allowed. Supported: {allowed_str}"

        return True, None

    def validate_file_size(self, file_size_bytes: int) -> tuple[bool, Optional[str]]:
        """
        Validate if a file size is within limits.

        Args:
            file_size_bytes: The file size in bytes

        Returns:
            Tuple of (is_valid, error_message)
        """
        if file_size_bytes <= 0:
            return False, "File size must be greater than 0"

        if file_size_bytes > self.max_file_size_bytes:
            max_mb = self.max_file_size_bytes // (1024 * 1024)
            file_mb = file_size_bytes / (1024 * 1024)
            return False, f"File size ({file_mb:.2f} MB) exceeds maximum allowed ({max_mb} MB)"

        return True, None

    def validate_file_mime_type(self, mime_type: str, filename: str = None) -> tuple[bool, Optional[str]]:
        """
        Validate if a file MIME type is allowed.

        Args:
            mime_type: The MIME type to validate
            filename: Optional filename for fallback validation

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not mime_type:
            if filename:
                # Fallback to extension validation
                return self.validate_file_extension(filename)
            return False, "MIME type is required"

        # Get constraints to access allowed MIME types
        constraints = self.get_constraints()
        allowed_mimes = constraints["constraints"]["allowed_mime_types"]

        if mime_type in allowed_mimes:
            return True, None

        # Some browsers may provide different MIME types for the same file
        # Fallback to extension validation
        if filename:
            return self.validate_file_extension(filename)

        return False, f"MIME type '{mime_type}' not allowed"


# Singleton instance
_upload_constraints_service = None


def get_upload_constraints_service() -> UploadConstraintsService:
    """Get singleton UploadConstraintsService instance."""
    global _upload_constraints_service
    if _upload_constraints_service is None:
        _upload_constraints_service = UploadConstraintsService()
    return _upload_constraints_service
