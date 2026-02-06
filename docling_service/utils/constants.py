"""Constants and file type configurations for Docling Service."""

# Supported file types for docling processing
# Note: HTML files are NOT supported by docling (it tries to process them as PDFs which fails)
SUPPORTED_FILE_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
}

# File types that should skip docling (already structured/text)
SKIP_DOCLING_TYPES = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
}

# Maximum file size in bytes (50 MB)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Processing timeout in seconds
DEFAULT_TIMEOUT_SECONDS = 270

# Model configuration
DEFAULT_MODEL = "granite-docling-258m"
