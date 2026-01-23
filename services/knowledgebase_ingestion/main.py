"""Knowledgebase Ingestion Service - Handles document uploads, R2 storage, and Gemini FileSearch."""
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Header, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, Field, validator
from typing import Optional, List, Dict, Any, Union
from google import genai
from google.genai import types
import os
import logging
from dotenv import load_dotenv
import json
import asyncio
import hashlib
import sys
import re
from pathlib import Path
from contextlib import asynccontextmanager

# ============================================================================
# VALIDATION CONSTANTS
# ============================================================================
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

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.config import settings
from shared import db

load_dotenv()

# Configure logging for containerized environments (Railway, Docker)
# Force output to stdout/stderr for proper log aggregation
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Explicitly use stdout
    ],
    force=True  # Override any existing configuration
)
logger = logging.getLogger(__name__)

# Log startup diagnostics
logger.info("="*60)
logger.info("KNOWLEDGEBASE INGESTION SERVICE STARTING UP")
logger.info("="*60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'development')}")

# Ensure shared utilities are importable and enable global exception logging
import sys
from pathlib import Path
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
except Exception:
    logger.debug("Could not adjust sys.path for shared imports")

from shared.utils import setup_global_exception_logging, register_fastapi_exception_handlers, dependency_unavailable_error, log_system_metrics, log_endpoint_request
setup_global_exception_logging("knowledgebase_ingestion")

# Validate required environment variables for this service
if not settings.gemini_api_key:
    raise dependency_unavailable_error("gemini_api_key", "Knowledgebase ingestion service requires GEMINI_API_KEY")

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Startup - Initialize database connections
        if settings.railway_postgres_url:
            try:
                await db.init_railway_db(settings.railway_postgres_url)
                logger.info("Railway PostgreSQL database initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Railway PostgreSQL: {e}")

        logger.info("🚀 Knowledgebase ingestion service started successfully")
        logger.info("🏥 Health check endpoint: /health")
        logger.info("📤 Upload endpoint: POST /upload")
        logger.info("📄 Files endpoint: GET /files")

        yield

        # Shutdown - Close database connections
        if db.railway_db:
            await db.railway_db.disconnect()
        logger.info("🛑 Knowledgebase ingestion service shutdown complete")
    except Exception as e:
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

app = FastAPI(
    title="Knowledgebase Ingestion Service",
    version="1.0.0",
    lifespan=lifespan
)

# Register FastAPI-level exception handlers to ensure stack traces are logged
register_fastapi_exception_handlers(app, "knowledgebase_ingestion")

# Custom validation error handler for better error messages
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return user-friendly validation error messages."""
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error.get("loc", []))
        message = error.get("msg", "Validation error")
        errors.append({"field": field, "message": message})
    
    logger.warning(f"Validation error for request: {errors}")
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "message": "Validation failed",
            "errors": errors
        }
    )

# Request logging middleware
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware to log all incoming requests with timing and status information."""
    start_time = time.time()
    request_id = f"{int(start_time * 1000000) % 1000000:06d}"  # Simple request ID

    # Log incoming request
    logger.info(f"📨 [{request_id}] {request.method} {request.url.path} - Client: {request.client.host if request.client else 'unknown'}")

    # Log headers (excluding sensitive ones)
    safe_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ['authorization', 'x-api-key', 'cookie']}
    if safe_headers:
        logger.debug(f"📋 [{request_id}] Headers: {dict(safe_headers)}")

    try:
        # Process the request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        if response.status_code >= 400:
            logger.warning(f"↩️ [{request_id}] Response: {response.status_code} - Path: {request.url.path} - Duration: {duration:.3f}s")
        else:
            logger.info(f"↩️ [{request_id}] Response: {response.status_code} - Duration: {duration:.3f}s")

        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"💥 [{request_id}] Request failed after {duration:.3f}s: {e}", exc_info=True)
        raise

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
genai_client = None
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY environment variable not set - Gemini-dependent endpoints will be unavailable")
else:
    try:
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("✅ Gemini client initialized successfully")
    except Exception as e:
        genai_client = None
        logger.error(f"❌ Failed to initialize Gemini client: {e}")

# R2 storage removed - files go directly to Gemini

class FileInfo(BaseModel):
    name: str
    display_name: str
    mime_type: str
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    expiration_time: Optional[str] = None
    size_bytes: Optional[str] = None
    sha256_hash: Optional[str] = None
    uri: Optional[str] = None
    state: Optional[str] = None
    db_record_id: Optional[str] = None
    source: Optional[str] = None  # 'upload' or 'scrape'
    original_filename: Optional[str] = None


class UploadResponse(BaseModel):
    success: bool
    file: Optional[FileInfo] = None
    message: str
    replaced_existing: bool = False


class ValidationError(BaseModel):
    field: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: List[ValidationError] = []


# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

def validate_file_extension(filename: str) -> tuple[bool, str]:
    """Validate file extension is allowed."""
    if not filename:
        return False, "Filename is required"
    
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if not ext:
        return False, "File must have an extension"
    
    if ext not in ALLOWED_FILE_EXTENSIONS:
        allowed_list = ', '.join(sorted(ALLOWED_FILE_EXTENSIONS))
        return False, f"File type '.{ext}' is not allowed. Allowed types: {allowed_list}"
    
    return True, ""


def validate_file_size(size_bytes: int) -> tuple[bool, str]:
    """Validate file size is within limits."""
    if size_bytes <= 0:
        return False, "File is empty"
    
    if size_bytes > MAX_FILE_SIZE_BYTES:
        file_mb = size_bytes / (1024 * 1024)
        return False, f"File size ({file_mb:.2f} MB) exceeds maximum allowed size of 1 MB"
    
    return True, ""


def validate_mime_type(mime_type: str, filename: str) -> tuple[bool, str]:
    """Validate MIME type is allowed."""
    if not mime_type:
        return True, ""  # Allow missing mime type, will be detected
    
    # Be lenient - if extension is valid, accept even if mime type is generic
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ALLOWED_FILE_EXTENSIONS:
        return True, ""
    
    if mime_type not in ALLOWED_MIME_TYPES:
        return False, f"MIME type '{mime_type}' is not allowed"
    
    return True, ""


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal and special characters."""
    # Remove path separators
    filename = os.path.basename(filename)
    # Remove potentially dangerous characters
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', filename)
    # Limit length
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:255-len(ext)] + ext
    return filename


def detect_mime_type_from_extension(filename: str, provided_mime_type: Optional[str] = None) -> str:
    """Detect proper MIME type from file extension, falling back to provided type or default."""
    import mimetypes
    
    # If provided MIME type is valid and not generic, use it
    if provided_mime_type and provided_mime_type != "application/octet-stream":
        return provided_mime_type
    
    # Map file extensions to MIME types (Gemini-compatible)
    # Only supported formats: Documents (.pdf, .docx, .txt), Spreadsheets (.xlsx, .csv), 
    # Presentations (.pptx), Code (.py, .js, .html, .json, .md)
    extension_to_mime = {
        # Documents
        'pdf': 'application/pdf',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'txt': 'text/plain',
        # Spreadsheets
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'csv': 'text/csv',
        # Presentations
        'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        # Code
        'py': 'text/x-python',
        'js': 'application/javascript',
        'html': 'text/html',
        'json': 'application/json',
        'md': 'text/markdown',
    }
    
    # Extract extension
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    
    # Use our mapping first
    if ext in extension_to_mime:
        return extension_to_mime[ext]
    
    # Fallback to mimetypes library
    guessed_type, _ = mimetypes.guess_type(filename)
    if guessed_type:
        return guessed_type
    
    # Last resort: return provided type or default
    return provided_mime_type or "application/octet-stream"


async def check_duplicate_file(sha256_hash: str, original_filename: str) -> Optional[Dict[str, Any]]:
    """Check if a file with the same hash or name already exists."""
    if not db.railway_db:
        return None
    
    try:
        # Check by hash first (exact duplicate)
        existing = await db.railway_db.fetchrow(
            """
            SELECT id, original_filename, display_name, sha256_hash, size_bytes, gemini_file_name,
                   COALESCE(version, 1) as version
            FROM file_uploads 
            WHERE sha256_hash = $1
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            sha256_hash
        )
        
        if existing:
            return {
                "id": str(existing['id']),
                "original_filename": existing['original_filename'],
                "display_name": existing['display_name'],
                "sha256_hash": existing['sha256_hash'],
                "size_bytes": existing['size_bytes'],
                "gemini_file_name": existing['gemini_file_name'],
                "version": existing['version'],
                "match_type": "hash"
            }
        
        # Check by filename (same name, different content)
        existing_by_name = await db.railway_db.fetchrow(
            """
            SELECT id, original_filename, display_name, sha256_hash, size_bytes, gemini_file_name,
                   COALESCE(version, 1) as version
            FROM file_uploads 
            WHERE original_filename = $1
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            original_filename
        )
        
        if existing_by_name:
            return {
                "id": str(existing_by_name['id']),
                "original_filename": existing_by_name['original_filename'],
                "display_name": existing_by_name['display_name'],
                "sha256_hash": existing_by_name['sha256_hash'],
                "size_bytes": existing_by_name['size_bytes'],
                "gemini_file_name": existing_by_name['gemini_file_name'],
                "version": existing_by_name['version'],
                "match_type": "filename"
            }
        
        return None
    except Exception as e:
        logger.warning(f"Error checking for duplicate file: {e}")
        return None


async def delete_existing_file(gemini_file_name: str, db_id: str):
    """Delete an existing file from Gemini and database."""
    try:
        # Delete from Gemini
        if genai_client and gemini_file_name:
            try:
                genai_client.files.delete(name=gemini_file_name)
                logger.info(f"Deleted old file from Gemini: {gemini_file_name}")
            except Exception as e:
                logger.warning(f"Failed to delete from Gemini: {e}")
        
        # Delete from database
        if db.railway_db:
            await db.railway_db.execute(
                "DELETE FROM file_uploads WHERE id = $1",
                db_id
            )
            logger.info(f"Deleted old file record from database: {db_id}")
            
    except Exception as e:
        logger.error(f"Error deleting existing file: {e}")


class FilesResponse(BaseModel):
    files: List[FileInfo]


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    log_endpoint_request("knowledgebase_ingestion", "health", request)
    return {"status": "healthy", "service": "knowledgebase_ingestion"}


@app.get("/upload/constraints")
async def get_upload_constraints():
    """
    Get file upload constraints for UI display.
    Returns maximum file size, allowed extensions, and MIME types.
    """
    return {
        "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
        "max_file_size_mb": 5,
        "max_file_size_display": "5 MB",
        "allowed_extensions": sorted(ALLOWED_FILE_EXTENSIONS),
        "allowed_mime_types": sorted(ALLOWED_MIME_TYPES),
        "supported_formats": {
            "documents": ["PDF", "DOCX", "TXT"],
            "spreadsheets": ["XLSX", "CSV"],
            "presentations": ["PPTX"],
            "code": ["PY", "JS", "HTML", "JSON", "MD"]
        },
        "supported_extensions": {
            "documents": [".pdf", ".docx", ".txt"],
            "spreadsheets": [".xlsx", ".csv"],
            "presentations": [".pptx"],
            "code": [".py", ".js", ".html", ".json", ".md"]
        }
    }


def calculate_sha256(file_path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


async def get_or_create_user(email: str) -> str:
    """Get user identifier for tracking purposes.
    
    Since the system uses admins and human_agents tables instead of a users table,
    we return the email as the user identifier for tracking/logging purposes.
    Anyone can upload files regardless of their role in the system.
    """
    if not email:
        logger.warning("No email provided for user identification")
        return None
    
    try:
        # Check if user exists in admins table
        admin_user = await db.railway_db.fetchrow(
            "SELECT email FROM admins WHERE email = $1",
            email
        )
        
        if admin_user:
            logger.debug(f"User {email} found in admins table")
            return email  # Return email as user identifier
        
        # Check if user exists in human_agents table
        agent_user = await db.railway_db.fetchrow(
            "SELECT email FROM human_agents WHERE email = $1",
            email
        )
        
        if agent_user:
            logger.debug(f"User {email} found in human_agents table")
            return email  # Return email as user identifier
        
        # User not in either table - still allow them to upload files
        # Just return their email as the identifier
        logger.debug(f"User {email} not found in admins/human_agents tables, using email as identifier")
        return email
    
    except Exception as e:
        logger.error(f"Error checking user tables for email {email}: {e}")
        # Even on database error, return email as fallback for tracking
        logger.warning(f"Database error - using email {email} as fallback user identifier")
        return email


async def _record_api_usage(
    user_id: Optional[str],
    provider: str,
    endpoint: str,
    method: str = "POST",
    status_code: int = 200,
    req_size: int = 0,
    res_size: int = 0,
    duration_ms: int = 0,
    metadata: Dict[str, Any] = None
):
    """Record API usage to the database."""
    if not db.railway_db:
        return

    try:
        await db.railway_db.execute(
            """
            INSERT INTO api_usage (
                api_provider, api_endpoint, http_method,
                request_size_bytes, response_size_bytes, status_code,
                user_email, duration_ms, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            provider, endpoint, method,
            req_size, res_size, status_code,
            user_id, duration_ms, json.dumps(metadata or {})
        )
    except Exception as e:
        logger.exception("Failed to record API usage: %s", e)

async def _stream_to_temp_file(file: UploadFile, original_filename: str) -> tuple[str, int]:
    """Stream an uploaded file to a temporary location."""
    import tempfile
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


# R2 storage removed - files go directly to Gemini


async def _process_with_gemini(tmp_path: str, file_display_name: str, original_filename: str, mime_type: str):
    """Upload to Gemini FileSearch and poll for processing completion.
    
    Args:
        tmp_path: Path to temporary file
        file_display_name: Display name for the file (custom name if provided)
        original_filename: Original filename (to be stored as metadata)
        mime_type: Detected MIME type (should already be properly detected)
    """
    # Double-check MIME type is not generic (fallback safety)
    final_mime_type = detect_mime_type_from_extension(original_filename, mime_type)
    
    if final_mime_type != mime_type:
        logger.warning(f"⚠️ [GEMINI] MIME type correction: {mime_type} -> {final_mime_type}")
    
    # Format display_name to include original filename as metadata
    # Format: "Display Name | original_filename.ext" or just "original_filename.ext" if no custom name
    # This ensures we can extract the original filename later from the display_name
    if file_display_name != original_filename:
        # Custom display name provided - include original filename as metadata
        gemini_display_name = f"{file_display_name} | {original_filename}"
    else:
        # No custom name - use original filename as display name
        gemini_display_name = original_filename
    
    logger.info(f"🤖 [GEMINI] Uploading to FileSearch - Display: {gemini_display_name}, Original: {original_filename}, MIME: {final_mime_type}...")
    uploaded_file = genai_client.files.upload(
        file=tmp_path,
        config=types.UploadFileConfig(
            display_name=gemini_display_name,
            mime_type=final_mime_type
        )
    )
    
    logger.info(f"✅ [GEMINI] Upload complete. File ID: {uploaded_file.name}, State: {uploaded_file.state.name}")
    logger.info(f"🔗 [GEMINI] URI: {getattr(uploaded_file, 'uri', 'N/A')}")
    
    final_state = uploaded_file.state.name
    gemini_processed_at = None
    
    try:
        for i in range(15):  # Poll for up to 30 seconds
            current_file = genai_client.files.get(name=uploaded_file.name)
            final_state = current_file.state.name
            logger.info(f"🔄 [GEMINI] Polling state (Attempt {i+1}/15): {final_state}")
            
            if final_state == "ACTIVE":
                from datetime import datetime
                gemini_processed_at = datetime.utcnow()
                logger.info("⚡ [GEMINI] Processing complete - File is now ACTIVE")
                break
            elif final_state == "FAILED":
                logger.error(f"❌ [GEMINI] Processing FAILED for {uploaded_file.name}")
                break
                
            await asyncio.sleep(2)
    except Exception as e:
        logger.warning(f"⚠️ [GEMINI] Error during polling: {e}")
        
    return uploaded_file, final_state, gemini_processed_at


async def _record_metadata(user_id: str, original_filename: str, file_display_name: str, 
                         file_ext: str, uploaded_file: Any, 
                         file_size: int, sha256_hash: str, 
                         final_state: str, gemini_processed_at: Any, mime_type: str, version: int = 1):
    """Persist file metadata and metrics to the PostgreSQL database."""
    db_record_id = None
    if not db.railway_db:
        logger.warning("⚠️ [DB] Database unavailable - Skipping metadata record")
        return None

    try:
        logger.info(f"🗄️ [DB] Saving metadata for {original_filename} (version {version})")
        db_record_id = await db.railway_db.fetchval(
            """
            INSERT INTO file_uploads (
                user_email, original_filename, display_name, file_extension,
                gemini_file_name, gemini_file_uri,
                mime_type, size_bytes, sha256_hash,
                gemini_upload_status, gemini_state,
                gemini_processed_at, expires_at, metadata, version
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING id
            """,
            user_id,
            original_filename,
            file_display_name,
            file_ext.lstrip('.'),
            uploaded_file.name,
            getattr(uploaded_file, 'uri', None),
            mime_type,
            file_size,
            sha256_hash,
            final_state.lower(),
            final_state,
            gemini_processed_at,
            uploaded_file.expiration_time if hasattr(uploaded_file, 'expiration_time') else None,
            json.dumps({'gemini_file_id': uploaded_file.name}),
            version
        )
        logger.info(f"✅ [DB] Record created with ID: {db_record_id} (version {version})")
        
        # Log metric
        await db.railway_db.execute(
            """
            INSERT INTO metrics (metric_type, metric_name, value, unit, user_email, file_upload_id, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            'file_upload', 'file_size_bytes', file_size, 'bytes', 
            user_id, db_record_id, json.dumps({'filename': original_filename})
        )
        logger.info(f"✅ [DB] Metric 'file_size_bytes' recorded for file {db_record_id}")
    except Exception as e:
        logger.error(f"❌ [DB] Error recording metadata (metrics might be missing): {e}")
        import traceback
        logger.error(traceback.format_exc())
        
    return db_record_id


import time
import logging
from fastapi import HTTPException, status

# Use a specific logger for this module
logger = logging.getLogger(__name__)

@app.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(None),
    user_email: Optional[str] = Header(None, alias="X-User-Email"),
    replace_existing: bool = Form(False)  # Whether to replace existing file with same name/hash
):
    """
    Modularized Document Ingestion Pipeline with structured logging and performance tracking.
    
    Args:
        file: The file to upload
        display_name: Optional display name for the file
        user_email: User email for tracking
        replace_existing: If True, replaces existing file with same name/hash
    
    Raises:
        HTTPException 400: Validation errors (file size, type, etc.)
        HTTPException 409: File already exists and replace_existing is False
        HTTPException 500: Internal server error
    """
    start_time = time.perf_counter()
    replaced_existing = False
    
    # Configuration Check
    if not genai_client:
        logger.critical("Upload failed: Gemini client not configured in environment.")
        from shared.utils import dependency_unavailable_error
        raise dependency_unavailable_error("gemini", "client not configured")

    # Initial State
    tmp_path = None
    original_filename = sanitize_filename(file.filename or "unknown_file")
    file_display_name = display_name or original_filename
    email = user_email or settings.default_user_email
    
    # Create a contextual prefix for logs to track this specific request
    log_context = {"upload_file_name": original_filename, "user_email": email}
    logger.info(f"Initiating upload pipeline for {original_filename}", extra=log_context)
    
    # ========================================================================
    # SERVER-SIDE VALIDATION
    # ========================================================================
    validation_errors = []
    
    # Validate file extension
    ext_valid, ext_error = validate_file_extension(original_filename)
    if not ext_valid:
        validation_errors.append({"field": "file", "message": ext_error})
    
    # Validate MIME type
    mime_valid, mime_error = validate_mime_type(file.content_type, original_filename)
    if not mime_valid:
        validation_errors.append({"field": "content_type", "message": mime_error})
    
    # Early validation check
    if validation_errors:
        logger.warning(f"Validation failed for {original_filename}: {validation_errors}", extra=log_context)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "File validation failed",
                "errors": validation_errors
            }
        )

    try:
        # Step 0: User Setup
        user_id = None
        if db.railway_db:
            user_id = await get_or_create_user(email)
            log_context["user_id"] = user_id
            logger.debug(f"User resolved to ID: {user_id}", extra=log_context)
        else:
            logger.warning("RAILWAY_DB is None. Checking config...", extra=log_context)
            url_configured = bool(settings.railway_postgres_url)
            logger.warning(f"Is RAILWAY_POSTGRES_URL configured in settings? {url_configured}", extra=log_context)
            if url_configured:
                masked_url = settings.railway_postgres_url.split('@')[-1] if '@' in settings.railway_postgres_url else "..."
                logger.warning(f"Configured URL host: {masked_url}", extra=log_context)

        # Step 1: Stream to disk
        logger.info(f"Streaming {original_filename} to local temp storage...", extra=log_context)
        tmp_path, file_size = await _stream_to_temp_file(file, original_filename)
        sha256_hash = calculate_sha256(tmp_path)
        log_context["sha256"] = sha256_hash
        logger.info(f"File streamed. Size: {file_size} bytes, Hash: {sha256_hash}", extra=log_context)
        
        # Detect proper MIME type from filename (important for Gemini compatibility)
        detected_mime_type = detect_mime_type_from_extension(original_filename, file.content_type)
        if detected_mime_type != (file.content_type or "application/octet-stream"):
            logger.info(f"🔍 MIME type detected: {file.content_type or 'None'} -> {detected_mime_type} (from extension)", extra=log_context)
        else:
            logger.info(f"✅ MIME type confirmed: {detected_mime_type} for {original_filename}", extra=log_context)
        
        # ====================================================================
        # VALIDATE FILE SIZE (after streaming to know actual size)
        # ====================================================================
        size_valid, size_error = validate_file_size(file_size)
        if not size_valid:
            logger.warning(f"File size validation failed: {size_error}", extra=log_context)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": size_error,
                    "errors": [{"field": "file", "message": size_error}]
                }
            )
        
        # ====================================================================
        # CHECK FOR DUPLICATE FILES
        # ====================================================================
        existing_file = await check_duplicate_file(sha256_hash, original_filename)
        if existing_file:
            match_type = existing_file.get("match_type", "unknown")

            if match_type == "hash":
                # Exact duplicate - same content, different filename
                # Allow this since user renamed the file - they might want multiple copies with different names
                logger.info(f"File with same content exists under different name '{existing_file['original_filename']}', allowing upload with new name '{original_filename}'", extra=log_context)
                # Continue with upload - don't raise error
            else:
                # Same filename, different content
                if not replace_existing:
                    logger.info(f"File with same name exists but different content: {existing_file['original_filename']}", extra=log_context)
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "message": f"A file named '{existing_file['original_filename']}' already exists with different content.",
                            "existing_file": existing_file,
                            "suggestion": "Set replace_existing=true to replace the existing file, or rename your file"
                        }
                    )
            
            # Replace existing file if requested
            if replace_existing:
                existing_version = existing_file.get('version', 1)
                new_version = existing_version + 1
                logger.info(f"Replacing existing file: {existing_file['gemini_file_name']} (version {existing_version} -> {new_version})", extra=log_context)
                await delete_existing_file(
                    existing_file.get('gemini_file_name'),
                    existing_file.get('id')
                )
                replaced_existing = True
                log_context["new_version"] = new_version

        # Track what has been successfully created for rollback
        gemini_file_created = None
        
        # Step 2: Process with Gemini (AI Processing) - files go directly to Gemini
        try:
            logger.info("Sending file to Gemini FileSearch API...", extra=log_context)
            uploaded_file, final_state, gemini_processed_at = await _process_with_gemini(
                tmp_path, file_display_name, original_filename, detected_mime_type
            )
            gemini_file_created = uploaded_file.name  # Track for potential rollback
            logger.info(f"Gemini processing finished. State: {final_state}", extra=log_context)
            
            # Track Gemini Usage
            await _record_api_usage(
                user_id, "gemini", "files.upload", "POST", 200,
                file_size, 0, 0, {"file_name": uploaded_file.name}
            )
        except Exception as gemini_error:
            logger.error(f"❌ Gemini Upload Failed: {gemini_error}", exc_info=True, extra=log_context)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Upload failed at Gemini processing: {str(gemini_error)}"
            )

        # Step 3: Record Metadata (PostgreSQL)
        try:
            # Determine version: increment if replacing, else default to 1
            file_version = log_context.get("new_version", 1)
            logger.info(f"Recording final metadata to PostgreSQL (version {file_version})...", extra=log_context)
            file_ext = os.path.splitext(original_filename)[1] or ".bin"
            db_record_id = await _record_metadata(
                user_id, original_filename, file_display_name, file_ext,
                uploaded_file, file_size, sha256_hash,
                final_state, gemini_processed_at, detected_mime_type, version=file_version
            )
        except Exception as db_error:
            logger.error(f"❌ PostgreSQL Record Failed: {db_error}", exc_info=True, extra=log_context)
            # Rollback Gemini upload
            if gemini_file_created and genai_client:
                try:
                    genai_client.files.delete(name=gemini_file_created)
                    logger.info(f"✅ Rollback: Deleted Gemini file {gemini_file_created}", extra=log_context)
                except Exception as rollback_err:
                    logger.warning(f"⚠️ Rollback failed for Gemini: {rollback_err}", extra=log_context)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Upload failed at PostgreSQL: {str(db_error)}. Gemini upload has been rolled back."
            )

        # Step 4: Finalize Response
        duration = time.perf_counter() - start_time
        logger.info(
            f"Pipeline successful for {original_filename} in {duration:.2f}s",
            extra={**log_context, "duration_sec": duration}
        )

        # Track Internal API Usage
        await _record_api_usage(
            user_id, "internal", "/upload", "POST", 200,
            file_size, 0, int(duration * 1000), {"filename": original_filename}
        )

        return UploadResponse(
            success=True,
            file=FileInfo(
                name=uploaded_file.name,
                display_name=uploaded_file.display_name,
                mime_type=uploaded_file.mime_type,
                create_time=uploaded_file.create_time.isoformat() if uploaded_file.create_time else None,
                update_time=uploaded_file.update_time.isoformat() if uploaded_file.update_time else None,
                expiration_time=uploaded_file.expiration_time.isoformat() if uploaded_file.expiration_time else None,
                size_bytes=str(uploaded_file.size_bytes or file_size),
                sha256_hash=sha256_hash,
                uri=getattr(uploaded_file, 'uri', None),
                state=final_state,
                db_record_id=str(db_record_id) if db_record_id else None,
                source='upload',
                original_filename=original_filename
            ),
            message=f"File {'replaced' if replaced_existing else 'processed'} successfully: {file_display_name}",
            replaced_existing=replaced_existing
        )

    except HTTPException:
        # Re-raise HTTP exceptions (these have specific error messages)
        raise
        
    except ValueError as ve:
        # Catch validation/input errors separately
        logger.warning(f"Validation error during upload: {ve}", extra=log_context)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    except Exception as e:
        # Log the full stack trace for unexpected system errors
        logger.error(
            f"Critical failure in ingestion pipeline: {type(e).__name__} - {e}", 
            exc_info=True, 
            extra=log_context
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"An internal error occurred during document processing: {type(e).__name__} - {str(e)}"
        )
        
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.debug(f"Temporary file deleted: {tmp_path}", extra=log_context)
            except Exception as cleanup_err:
                logger.warning(f"Failed to delete temp file {tmp_path}: {cleanup_err}", extra=log_context)

@app.get("/files")
async def list_files(
    source: Optional[str] = Query(None, description="Filter by source: 'upload', 'scrape', or None for all"),
    include_gemini: bool = Query(True, description="Include Gemini FileSearch files")
):
    """
    List all files from database (file_uploads + scraped_websites tables).
    Returns combined list with source type, size, and metadata.
    """
    file_list = []
    
    # Get files from database if available
    if db.railway_db:
        try:
            # Get uploaded files
            if source is None or source == 'upload':
                uploaded_files = await db.railway_db.fetch(
                    """
                    SELECT 
                        id, original_filename, display_name, file_extension,
                        mime_type, size_bytes, sha256_hash,
                        gemini_file_name, gemini_file_uri, gemini_state,
                        created_at, uploaded_at, updated_at,
                        COALESCE(version, 1) as version
                    FROM file_uploads
                    ORDER BY created_at DESC
                    """
                )
                
                for f in uploaded_files:
                    file_list.append({
                        "key": str(f['id']),
                        "id": str(f['id']),
                        "name": f['original_filename'],
                        "original_name": f['original_filename'],
                        "display_name": f['display_name'],
                        "file_type": f['file_extension'],
                        "type": f['file_extension'],
                        "mime_type": f['mime_type'],
                        "size": f['size_bytes'] or 0,
                        "size_bytes": f['size_bytes'] or 0,
                        "sha256_hash": f['sha256_hash'],
                        "gemini_file_name": f['gemini_file_name'],
                        "gemini_file_uri": f['gemini_file_uri'],
                        "status": f['gemini_state'] or 'uploaded',
                        "source": "upload",
                        "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                        "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None,
                        "last_modified": f['uploaded_at'].isoformat() if f['uploaded_at'] else None,
                        "version": f['version'] or 1,
                    })
            
            # Get scraped websites
            if source is None or source == 'scrape':
                scraped_files = await db.railway_db.fetch(
                    """
                    SELECT 
                        id, original_url, domain, title,
                        mime_type, size_bytes, pages_scraped, content_length,
                        gemini_file_name, gemini_file_uri, gemini_state,
                        created_at, scraped_at, updated_at,
                        COALESCE(version, 1) as version
                    FROM scraped_websites
                    ORDER BY created_at DESC
                    """
                )
                
                for f in scraped_files:
                    # Generate a display name from URL
                    display_name = f['title'] or f['domain'] or f['original_url']
                    file_list.append({
                        "key": str(f['id']),
                        "id": str(f['id']),
                        "name": display_name,
                        "original_name": display_name,
                        "display_name": display_name,
                        "file_type": "url",
                        "type": "url",
                        "mime_type": f['mime_type'] or "text/markdown",
                        "size": f['size_bytes'] or f['content_length'] or 0,
                        "size_bytes": f['size_bytes'] or f['content_length'] or 0,
                        "source_url": f['original_url'],
                        "url": f['original_url'],
                        "domain": f['domain'],
                        "pages_scraped": f['pages_scraped'],
                        "gemini_file_name": f['gemini_file_name'],
                        "gemini_file_uri": f['gemini_file_uri'],
                        "status": f['gemini_state'] or 'scraped',
                        "source": "scrape",
                        "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                        "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None,
                        "last_modified": f['scraped_at'].isoformat() if f['scraped_at'] else None,
                        "version": f['version'] or 1,
                    })
            
            logger.info(f"Retrieved {len(file_list)} files from database")
            
        except Exception as e:
            logger.error(f"Error fetching from database: {e}")
            # Fall back to Gemini if database fails
    
    # NOTE: No longer including Gemini-only files in the file list
    # Only database-backed files (from file_uploads and scraped_websites tables) are returned
    
    return {
        "files": file_list,
        "count": len(file_list),
        "sources": {
            "upload": len([f for f in file_list if f.get("source") == "upload"]),
            "scrape": len([f for f in file_list if f.get("source") == "scrape"]),
            "gemini": len([f for f in file_list if f.get("source") == "gemini"]),
        },
        "total_size_bytes": sum(f.get("size_bytes", 0) or 0 for f in file_list)
    }

@app.get("/files/metadata")
async def list_files_metadata(
    user_email: Optional[str] = Header(None, alias="X-User-Email")
):
    """
    List all uploaded files with metadata from database.

    Args:
        user_email: User email for access tracking
    """
    if not railway_db:
        from shared.utils import dependency_unavailable_error
        raise dependency_unavailable_error("database", "database not configured")

    try:
        files = await db.railway_db.fetch(
            """
            SELECT id, original_filename, display_name, file_extension, mime_type,
                   size_bytes, created_at, gemini_file_name
            FROM file_uploads
            ORDER BY created_at DESC
            """
        )

        file_list = []
        for f in files:
            file_info = {
                "id": str(f["id"]),
                "original_filename": f["original_filename"],
                "display_name": f["display_name"],
                "file_extension": f["file_extension"],
                "mime_type": f["mime_type"],
                "size_bytes": f["size_bytes"],
                "created_at": f["created_at"].isoformat() if f["created_at"] else None,
                "gemini_file_name": f["gemini_file_name"]
            }

            file_list.append(file_info)

        return {
            "files": file_list,
            "total_count": len(file_list)
        }
    except Exception as e:
        logger.error(f"Error listing files metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")

@app.get("/status")
async def get_service_status():
    """Get service status and configuration information."""
    return {
        "service": "knowledgebase_ingestion",
        "status": "healthy",
        "gemini_configured": genai_client is not None,
        "database_configured": db.railway_db is not None,
        "version": "1.0.0"
    }

# R2 storage removed - download and signed URL endpoints removed


@app.delete("/files/{file_id}")
async def delete_file(file_id: str):
    """Delete a file from Gemini FileSearch and database.

    This function attempts to delete from both storage layers independently.
    If one fails, it continues with the other (no rollback).

    Args:
        file_id: The database file ID (UUID) or Gemini file name (for Gemini-only files)

    Returns:
        Dict with success status and details of what was deleted/failed
    """
    logger.info(f"🗑️ Starting deletion of file with ID: {file_id}")

    if not genai_client:
        from shared.utils import dependency_unavailable_error
        raise dependency_unavailable_error("gemini", "client not configured")

    # Check if this is a Gemini-only file (file_id starts with "files/")
    if file_id.startswith("files/"):
        # This is a Gemini-only file, no database record exists
        gemini_file_name = file_id
        original_filename = "Gemini-only file"
        table_name = "gemini_only"
        logger.info(f"🗑️ Detected Gemini-only file: {gemini_file_name}")
    else:
        # This should be a database UUID, look it up
        if not db.railway_db:
            raise HTTPException(status_code=500, detail="Database not available")

        # Try to find the file by database ID - track which table it came from
        file_record = await db.railway_db.fetchrow(
            "SELECT gemini_file_name, original_filename, 'file_uploads' as table_name FROM file_uploads WHERE id = $1",
            file_id
        )
        table_name = 'file_uploads'

        if not file_record:
            # Try scraped_websites table as well
            file_record = await db.railway_db.fetchrow(
                "SELECT gemini_file_name, original_url as original_filename, 'scraped_websites' as table_name FROM scraped_websites WHERE id = $1",
                file_id
            )
            if file_record:
                table_name = 'scraped_websites'

        if not file_record or not file_record.get('gemini_file_name'):
            logger.warning(f"File with ID {file_id} not found in database")
            raise HTTPException(status_code=404, detail="File not found in database")

        gemini_file_name = file_record['gemini_file_name']
        original_filename = file_record.get('original_filename', 'Unknown')

    gemini_file_name = file_record['gemini_file_name']
    original_filename = file_record.get('original_filename', 'Unknown')
    logger.info(f"🗑️ Found file in database: ID={file_id}, gemini_file_name='{gemini_file_name}', original_filename='{original_filename}', table='{table_name}'")
    
    # Verify gemini_file_name format (should start with 'files/')
    if not gemini_file_name.startswith('files/'):
        logger.warning(f"⚠️ Unexpected gemini_file_name format for file {file_id}: '{gemini_file_name}' (expected format: 'files/...')")

    # Track deletion results for each storage layer
    deletion_results = {
        "gemini": {"success": False, "error": None},
        "postgres": {"success": False, "error": None}
    }

    # Step 1: Delete from Gemini FileSearch (no rollback on failure)
    try:
        # First verify the file exists in Gemini before attempting deletion
        try:
            file_info = genai_client.files.get(name=gemini_file_name)
            logger.info(f"🔍 Found file in Gemini: {gemini_file_name}, state: {file_info.state.name}")
        except Exception as get_error:
            error_str = str(get_error)
            # Check if it's a 403/404 (file doesn't exist or permission denied)
            if "403" in error_str or "404" in error_str or "PERMISSION_DENIED" in error_str or "NOT_FOUND" in error_str:
                logger.warning(f"⚠️ File {gemini_file_name} not found in Gemini (may have been already deleted or expired): {error_str}")
                deletion_results["gemini"]["error"] = f"File not found in Gemini: {error_str}"
                # Don't treat this as a critical error - continue with database deletion
            else:
                # Re-raise if it's a different error
                raise
        
        # File exists, proceed with deletion
        genai_client.files.delete(name=gemini_file_name)
        deletion_results["gemini"]["success"] = True
        logger.info(f"✅ Deleted file from Gemini FileSearch: {gemini_file_name}")
    except Exception as e:
        error_str = str(e)
        # Handle 403/404 errors gracefully
        if "403" in error_str or "404" in error_str or "PERMISSION_DENIED" in error_str or "NOT_FOUND" in error_str:
            logger.warning(f"⚠️ File {gemini_file_name} not found in Gemini (may have been already deleted): {error_str}")
            deletion_results["gemini"]["error"] = f"File not found in Gemini: {error_str}"
        else:
            deletion_results["gemini"]["error"] = error_str
            logger.warning(f"⚠️ Failed to delete from Gemini FileSearch: {e} (continuing with database deletion)")

    # Step 2: Delete from database (skip for Gemini-only files)
    if db.railway_db and table_name != 'gemini_only':
        try:
            # Delete the file record by ID using the tracked table name
            if table_name == 'file_uploads':
                result = await db.railway_db.execute(
                    "DELETE FROM file_uploads WHERE id = $1",
                    file_id
                )
                logger.info(f"✅ Deleted from file_uploads table: {result}")
            elif table_name == 'scraped_websites':
                result = await db.railway_db.execute(
                    "DELETE FROM scraped_websites WHERE id = $1",
                    file_id
                )
                logger.info(f"✅ Deleted from scraped_websites table: {result}")
            else:
                logger.warning(f"⚠️ Unknown table name: {table_name}, attempting both tables")
                # Fallback: try both tables
                try:
                    result = await db.railway_db.execute(
                        "DELETE FROM file_uploads WHERE id = $1",
                        file_id
                    )
                    logger.info(f"✅ Deleted from file_uploads table (fallback): {result}")
                except:
                    result = await db.railway_db.execute(
                        "DELETE FROM scraped_websites WHERE id = $1",
                        file_id
                    )
                    logger.info(f"✅ Deleted from scraped_websites table (fallback): {result}")

            deletion_results["postgres"]["success"] = True
        except Exception as e:
            deletion_results["postgres"]["error"] = str(e)
            logger.warning(f"⚠️ Failed to delete from database: {e}")

    # Determine overall success
    if table_name == 'gemini_only':
        # For Gemini-only files, success is based only on Gemini deletion
        overall_success = deletion_results["gemini"]["success"]
    else:
        # For database-backed files, at least one deletion should succeed
        overall_success = any(result["success"] for result in deletion_results.values())
    
    # Build response message
    success_parts = []
    failed_parts = []
    
    if deletion_results["gemini"]["success"]:
        success_parts.append("Gemini")
    elif deletion_results["gemini"]["error"]:
        failed_parts.append(f"Gemini: {deletion_results['gemini']['error']}")
    
    if deletion_results["postgres"]["success"]:
        success_parts.append("PostgreSQL")
    elif deletion_results["postgres"]["error"]:
        failed_parts.append(f"PostgreSQL: {deletion_results['postgres']['error']}")

    # Build response message with more context
    message = f"File deletion (ID: {file_id}, Gemini: {gemini_file_name}): "
    if success_parts:
        message += f"Deleted from {', '.join(success_parts)}"
    if failed_parts:
        # Check if Gemini failure is due to file not found (not critical)
        gemini_error = deletion_results.get("gemini", {}).get("error", "")
        if "not found" in gemini_error.lower() or "permission_denied" in gemini_error.lower():
            # File not found in Gemini is acceptable - it may have been already deleted
            message += f". Note: {gemini_error}"
        else:
            message += f". Failed: {'; '.join(failed_parts)}"

    # Consider deletion successful if database deletion succeeded, even if Gemini file was not found
    # (file may have been already deleted from Gemini or expired)
    db_success = deletion_results.get("postgres", {}).get("success", False)
    gemini_success = deletion_results.get("gemini", {}).get("success", False)
    gemini_error = deletion_results.get("gemini", {}).get("error")
    is_gemini_not_found = gemini_error and ("not found" in gemini_error.lower() or "permission_denied" in gemini_error.lower())
    
    if db_success:
        # Database deletion succeeded - this is the most important
        logger.info(f"✅ File {file_id} deletion result: Gemini={'success' if gemini_success else ('not_found' if is_gemini_not_found else 'failed')}, DB=success")
        return {
            "success": True,
            "message": message,
            "details": deletion_results
        }
    elif overall_success:
        # At least one deletion succeeded
        logger.info(f"✅ File {file_id} deletion result: Gemini={gemini_success}, DB={db_success}")
        return {
            "success": True,
            "message": message,
            "details": deletion_results
        }
    else:
        # All deletions failed
        logger.error(f"❌ File {file_id} deletion failed completely: {message}")
        raise HTTPException(
            status_code=500,
            detail=message
        )


if __name__ == "__main__":
    import uvicorn
    # Port selection order: Service-specific -> Railway PORT -> Default 8001
    port = int(os.getenv("KB_INGESTION_PORT", os.getenv("PORT", "8001")))
    logger.info(f"🚀 Starting knowledgebase_ingestion service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
