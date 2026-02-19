# VALIDATION CONSTANTS
# Note: These constants are used as fallback defaults.
# The authoritative source is the UploadConstraintsService (upload_constraints_service.py)
# which can be configured via environment variables for production flexibility.

import os

# Max file size (configurable via MAX_FILE_SIZE_MB env var, defaults to 100MB)
_MAX_SIZE_MB = int(os.getenv('MAX_FILE_SIZE_MB', '100'))
MAX_FILE_SIZE_BYTES = _MAX_SIZE_MB * 1024 * 1024

# Allowed file extensions (configurable via ALLOWED_FILE_EXTENSIONS env var)
ALLOWED_FILE_EXTENSIONS = [
    # Documents
    'pdf', 'docx', 'doc', 'txt', 'rtf',
    # Spreadsheets
    'xlsx', 'xls', 'csv', 'tsv',
    # Presentations
    'pptx', 'ppt',
    # Code/Web
    'py', 'js', 'ts', 'html', 'htm', 'json', 'md', 'yaml', 'yml', 'xml',
    # Archives
    'zip', 'tar', 'gz',
]

ALLOWED_MIME_TYPES = [
    # Documents
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.template',
    'application/msword',
    'text/plain',
    'application/rtf',
    'text/rtf',
    # Spreadsheets
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.template',
    'application/vnd.ms-excel',
    'text/csv',
    'text/tab-separated-values',
    # Presentations
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/vnd.openxmlformats-officedocument.presentationml.template',
    'application/vnd.ms-powerpoint',
    # Code/Web
    'text/x-python',
    'application/javascript',
    'text/javascript',
    'text/typescript',
    'text/html',
    'application/xml',
    'text/xml',
    'application/json',
    'text/markdown',
    'application/yaml',
    'application/x-yaml',
    'text/yaml',
    # Archives
    'application/zip',
    'application/x-zip-compressed',
    'application/x-tar',
    'application/gzip',
    'application/x-gzip',
]
