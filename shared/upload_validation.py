"""
Shared upload constraints and Pydantic validation for knowledgebase ingestion.

This module is importable from knowledgebase-ingestion and celery-file-worker,
so upload validation has one implementation and one supported-file list.
"""
import os
from dataclasses import dataclass
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, model_validator

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("upload_validation", "shared")


@dataclass
class FileTypeConstraint:
    extension: str
    mime_types: List[str]
    category: str
    description: str


class UploadConstraintsService:
    ALWAYS_ALLOWED_IMAGE_EXTENSIONS = [
        "png",
        "jpg",
        "jpeg",
        "webp",
        "gif",
        "bmp",
        "tif",
        "tiff",
        "svg",
    ]

    SUPPORTED_FILE_TYPES = {
        "pdf": FileTypeConstraint("pdf", ["application/pdf"], "document", "PDF Document"),
        "docx": FileTypeConstraint(
            "docx",
            [
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.template",
            ],
            "document",
            "Microsoft Word Document",
        ),
        "doc": FileTypeConstraint("doc", ["application/msword"], "document", "Microsoft Word 97-2003 Document"),
        "txt": FileTypeConstraint("txt", ["text/plain"], "document", "Plain Text"),
        "rtf": FileTypeConstraint("rtf", ["application/rtf", "text/rtf"], "document", "Rich Text Format"),
        "xlsx": FileTypeConstraint(
            "xlsx",
            [
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
            ],
            "spreadsheet",
            "Microsoft Excel Spreadsheet",
        ),
        "xls": FileTypeConstraint("xls", ["application/vnd.ms-excel"], "spreadsheet", "Microsoft Excel 97-2003 Spreadsheet"),
        "csv": FileTypeConstraint("csv", ["text/csv"], "spreadsheet", "Comma-Separated Values"),
        "tsv": FileTypeConstraint("tsv", ["text/tab-separated-values"], "spreadsheet", "Tab-Separated Values"),
        "pptx": FileTypeConstraint(
            "pptx",
            [
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.openxmlformats-officedocument.presentationml.template",
            ],
            "presentation",
            "Microsoft PowerPoint Presentation",
        ),
        "ppt": FileTypeConstraint("ppt", ["application/vnd.ms-powerpoint"], "presentation", "Microsoft PowerPoint 97-2003 Presentation"),
        "py": FileTypeConstraint("py", ["text/x-python", "text/plain"], "code", "Python Code"),
        "js": FileTypeConstraint("js", ["application/javascript", "text/javascript", "text/plain"], "code", "JavaScript Code"),
        "ts": FileTypeConstraint("ts", ["text/typescript", "text/plain"], "code", "TypeScript Code"),
        "html": FileTypeConstraint("html", ["text/html"], "web", "HTML Document"),
        "htm": FileTypeConstraint("htm", ["text/html"], "web", "HTML Document"),
        "xml": FileTypeConstraint("xml", ["application/xml", "text/xml"], "web", "XML Document"),
        "json": FileTypeConstraint("json", ["application/json", "text/plain"], "code", "JSON Data"),
        "md": FileTypeConstraint("md", ["text/markdown", "text/plain"], "document", "Markdown Document"),
        "yaml": FileTypeConstraint("yaml", ["application/yaml", "application/x-yaml", "text/yaml", "text/plain"], "code", "YAML Configuration"),
        "yml": FileTypeConstraint("yml", ["application/yaml", "application/x-yaml", "text/yaml", "text/plain"], "code", "YAML Configuration"),
        "zip": FileTypeConstraint("zip", ["application/zip", "application/x-zip-compressed"], "archive", "ZIP Archive"),
        "tar": FileTypeConstraint("tar", ["application/x-tar"], "archive", "TAR Archive"),
        "gz": FileTypeConstraint("gz", ["application/gzip", "application/x-gzip"], "archive", "GZIP Compressed File"),
        "tar.gz": FileTypeConstraint("tar.gz", ["application/gzip", "application/x-gzip"], "archive", "Tar GZip Archive"),
        "png": FileTypeConstraint("png", ["image/png"], "image", "PNG Image"),
        "jpg": FileTypeConstraint("jpg", ["image/jpeg"], "image", "JPEG Image"),
        "jpeg": FileTypeConstraint("jpeg", ["image/jpeg"], "image", "JPEG Image"),
        "webp": FileTypeConstraint("webp", ["image/webp"], "image", "WebP Image"),
        "gif": FileTypeConstraint("gif", ["image/gif"], "image", "GIF Image"),
        "bmp": FileTypeConstraint("bmp", ["image/bmp", "image/x-ms-bmp"], "image", "Bitmap Image"),
        "tif": FileTypeConstraint("tif", ["image/tiff"], "image", "TIFF Image"),
        "tiff": FileTypeConstraint("tiff", ["image/tiff"], "image", "TIFF Image"),
        "svg": FileTypeConstraint("svg", ["image/svg+xml"], "image", "SVG Image"),
    }

    def __init__(self):
        max_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
        self.max_file_size_bytes = max_size_mb * 1024 * 1024

        allowed_exts_env = os.getenv("ALLOWED_FILE_EXTENSIONS", "")
        if allowed_exts_env:
            configured_extensions = [ext.strip().lower() for ext in allowed_exts_env.split(",") if ext.strip()]
            self.allowed_extensions = list(dict.fromkeys(
                configured_extensions + self.ALWAYS_ALLOWED_IMAGE_EXTENSIONS
            ))
        else:
            self.allowed_extensions = list(self.SUPPORTED_FILE_TYPES.keys())

    def get_constraints(self) -> Dict[str, Any]:
        allowed_mime_types = []
        extensions_metadata = []

        for ext in self.allowed_extensions:
            constraint = self.SUPPORTED_FILE_TYPES.get(ext.lower())
            if not constraint:
                logger.warning(f"⚠️ [CONSTRAINTS] Unknown extension: {ext}")
                continue
            allowed_mime_types.extend(constraint.mime_types)
            extensions_metadata.append({
                "extension": constraint.extension,
                "category": constraint.category,
                "description": constraint.description,
                "mime_types": constraint.mime_types,
            })

        return {
            "success": True,
            "constraints": {
                "max_file_size": self.max_file_size_bytes,
                "max_file_size_display": f"{self.max_file_size_bytes // (1024 * 1024)} MB",
                "max_file_size_mb": self.max_file_size_bytes // (1024 * 1024),
                "allowed_extensions": self.allowed_extensions,
                "allowed_mime_types": list(set(allowed_mime_types)),
                "supported_file_types": extensions_metadata,
                "file_categories": self._get_categories_summary(),
            },
        }

    def _get_categories_summary(self) -> Dict[str, List[Dict[str, str]]]:
        categories = {}
        for ext in self.allowed_extensions:
            constraint = self.SUPPORTED_FILE_TYPES.get(ext.lower())
            if not constraint:
                continue
            categories.setdefault(constraint.category, []).append({
                "extension": ext,
                "description": constraint.description,
            })
        return categories


_upload_constraints_service = None


def get_upload_constraints_service() -> UploadConstraintsService:
    global _upload_constraints_service
    if _upload_constraints_service is None:
        _upload_constraints_service = UploadConstraintsService()
    return _upload_constraints_service


class UploadValidationInput(BaseModel):
    """Single Pydantic validator for knowledgebase file upload constraints."""

    model_config = ConfigDict(str_strip_whitespace=True)

    filename: str
    mime_type: str = ""
    size_bytes: int

    @model_validator(mode="after")
    def validate_upload_constraints(self) -> "UploadValidationInput":
        constraints = get_upload_constraints_service().get_constraints()["constraints"]
        allowed_extensions = constraints["allowed_extensions"]
        allowed_mime_types = constraints["allowed_mime_types"]
        max_file_size = constraints["max_file_size"]

        if not self.filename:
            raise ValueError("Filename is required")

        parts = self.filename.lower().split(".")
        if len(parts) < 2:
            raise ValueError("Filename must have an extension")

        extension = parts[-1]
        if len(parts) > 2 and extension == "gz" and parts[-2] == "tar":
            extension = "tar.gz"

        if extension not in allowed_extensions:
            allowed_list = ", ".join(sorted(allowed_extensions))
            raise ValueError(f"File type '.{extension}' not allowed. Supported: {allowed_list}")

        if self.mime_type and self.mime_type not in allowed_mime_types:
            return self

        if self.size_bytes <= 0:
            raise ValueError("File size must be greater than 0")

        if self.size_bytes > max_file_size:
            max_mb = max_file_size // (1024 * 1024)
            file_mb = self.size_bytes / (1024 * 1024)
            raise ValueError(
                f"File size ({file_mb:.2f} MB) exceeds maximum allowed ({max_mb} MB)"
            )

        return self
