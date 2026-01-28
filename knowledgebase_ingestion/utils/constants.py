# VALIDATION CONSTANTS

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5MB

ALLOWED_FILE_EXTENSIONS = [
    # Documents
    'pdf', 'docx', 'txt',
    # Spreadsheets
    'xlsx', 'csv',
    # Presentations
    'pptx',
    # Code
    'py', 'js', 'html', 'json', 'md',
]

ALLOWED_MIME_TYPES = [
    # Documents
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
    'text/plain',  # .txt
    # Spreadsheets
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
    'text/csv',  # .csv
    # Presentations
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # .pptx
    # Code
    'text/x-python',  # .py
    'application/javascript',  # .js
    'text/javascript',  # .js (alternative)
    'text/html',  # .html
    'application/json',  # .json
    'text/markdown',  # .md
]
