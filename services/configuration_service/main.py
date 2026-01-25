"""
Configuration Service - Handles chatbot and widget configuration management
"""
from fastapi import FastAPI, HTTPException, Request, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, validator, Field
from typing import List, Optional, Union
import os
import logging
import tempfile
import sys
import re
from datetime import datetime
try:
    import bleach
except ImportError:
    # Fallback if bleach is not available
    def clean(text, tags=[], attributes={}, strip=True):
        return text.strip() if strip else text
    bleach = type('bleach', (), {'clean': staticmethod(clean)})()
try:
    from email_validator import validate_email, EmailNotValidError
except ImportError:
    # Fallback if email_validator is not installed
    def validate_email(email, check_deliverability=True):
        # Basic email validation fallback
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_regex, email):
            raise ValueError('Invalid email format')
        return {'email': email}
    EmailNotValidError = ValueError
import json
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import asyncio
import asyncpg
from asyncpg import exceptions as asyncpg_exceptions

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import init_railway_db, close_databases, railway_db
from shared.utils import validate_environment, wait_for_railway_network, service_status
from shared.auth_middleware import get_current_user
from shared.r2_storage import R2Storage
load_dotenv()

# Lock for database initialization to prevent race conditions
_db_init_lock = asyncio.Lock()

# R2 Storage instance
r2_storage: Optional[R2Storage] = None

async def init_database_schema(database_url: str):
    """Initialize database schema if tables don't exist"""
    try:
        conn = await asyncpg.connect(database_url)

        # Check if widget_configuration table exists (main schema indicator)
        widget_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'widget_configuration')"
        )

        if not widget_exists:
            logger.info("📊 Database tables not found, initializing schema...")

            # Read and execute schema
            schema_path = Path(__file__).parent.parent.parent / "sql" / "schema_3nf.sql"
            if schema_path.exists():
                schema_sql = schema_path.read_text()
                await conn.execute(schema_sql)
                logger.info("✅ Database schema initialized successfully")
            else:
                logger.warning(f"⚠️ Schema file not found: {schema_path}")
        else:
            logger.info("✅ Database tables already exist")

        # Check for token_usage_log table (added later) and create if missing
        token_log_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'token_usage_log')"
        )

        if not token_log_exists:
            logger.info("📊 token_usage_log table not found, creating...")

            # Read and execute token usage log migration
            migration_path = Path(__file__).parent.parent.parent.parent / "add_token_usage_log_migration.sql"
            if migration_path.exists():
                migration_sql = migration_path.read_text()
                await conn.execute(migration_sql)
                logger.info("✅ token_usage_log table created successfully")
            else:
                logger.warning(f"⚠️ Token usage migration file not found: {migration_path}")

                # Create table directly if migration file not found
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS token_usage_log (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE,
                        message_id UUID REFERENCES chat_messages(id) ON DELETE CASCADE,
                        provider VARCHAR(50) NOT NULL,
                        model VARCHAR(100),
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        cost_cents INTEGER DEFAULT 0,
                        api_call_type VARCHAR(50),
                        request_metadata JSONB,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS idx_token_usage_log_session ON token_usage_log(session_id);
                    CREATE INDEX IF NOT EXISTS idx_token_usage_log_provider ON token_usage_log(provider);
                    CREATE INDEX IF NOT EXISTS idx_token_usage_log_created_at ON token_usage_log(created_at DESC);
                    COMMENT ON TABLE token_usage_log IS 'Detailed token usage log for correlating usage with specific API calls';
                """)
                logger.info("✅ token_usage_log table created directly")
        else:
            logger.info("✅ token_usage_log table already exists")

        await conn.close()

    except Exception as e:
        logger.error(f"❌ Database schema initialization error: {e}")
        raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)
logger = logging.getLogger(__name__)

# Input sanitization function
def sanitize_text_input(text: str, max_length: int = 1000) -> str:
    """Sanitize user input to prevent XSS and other attacks"""
    if not text:
        return text

    # Configure allowed tags and attributes
    allowed_tags = []  # No HTML tags allowed for configuration text
    allowed_attributes = {}

    # Clean the text
    sanitized = bleach.clean(
        text,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=True
    )

    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]

    return sanitized.strip()

# Audit logging function
async def log_configuration_change(user_email: str, action: str, details: dict, ip_address: str = None):
    """Log configuration changes for audit purposes"""
    try:
        async with get_db_connection() as conn:
            await conn.execute(
                """
                INSERT INTO configuration_audit_log
                (user_email, action, details, ip_address, timestamp)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_email, action, json.dumps(details), ip_address, datetime.utcnow()
            )
    except Exception as e:
        logger.warning(f"Failed to log configuration change: {e}")

# Business logic validation function (moved after class definitions)

# Log startup diagnostics
logger.info("="*60)
logger.info("CONFIGURATION SERVICE STARTING UP")
logger.info("="*60)
logger.info(f"Python version: {sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info(f"Environment: {os.getenv('RAILWAY_ENVIRONMENT', 'development')}")

# Get port configuration
PORT = int(os.getenv('CONFIGURATION_SERVICE_PORT', os.getenv('PORT', '8004')))
logger.info(f"PORT being used: {PORT}")

# Database dependency for lazy initialization
async def get_database():
    """Get database connection with lazy initialization."""
    from shared.db import railway_db, init_railway_db
    
    # If database is already initialized and healthy, return it
    if railway_db is not None:
        if hasattr(railway_db, '_pool') and railway_db._pool is not None:
            try:
                async with railway_db._pool.acquire() as conn:
                    await conn.execute("SELECT 1")  # Health check
                return railway_db
            except Exception as e:
                logger.warning(f"⚠️ Database health check failed: {e}")
    
    # Initialize database if not available or unhealthy
    database_url = getattr(app.state, 'database_url', None)
    if not database_url:
        raise HTTPException(status_code=503, detail="Database not configured")
    
    try:
        return await init_railway_db(database_url)
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise HTTPException(status_code=503, detail="Database connection failed")

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events with Railway fixes."""
    try:
        service_status.set_status("starting")

        # Validate environment variables
        try:
            validate_environment()
        except ValueError as e:
            logger.error(f"❌ Environment validation failed: {e}")
            service_status.set_status("error")
            raise

        # Wait for Railway network initialization
        await wait_for_railway_network()

        # Store database URL for lazy initialization
        database_url = (
            os.getenv("DATABASE_URL") or
            os.getenv("RAILWAY_POSTGRES_URL") or
            os.getenv("POSTGRES_URL")
        )

        if database_url:
            # Initialize database connection pool during startup
            app.state.database_url = database_url
            try:
                from shared.db import init_railway_db
                await init_railway_db(database_url)
                logger.info("✅ Database connection pool initialized during startup")
            except Exception as e:
                logger.error(f"❌ Failed to initialize database pool: {e}")
                # Don't fail startup, but log the error
            
            # Initialize database schema if needed
            try:
                await init_database_schema(database_url)
                logger.info("✅ Database schema initialized/verified")
            except Exception as e:
                logger.error(f"❌ Failed to initialize database schema: {e}")
                # Don't fail startup, but log the error
        else:
            logger.error("❌ DATABASE_URL, RAILWAY_POSTGRES_URL, or POSTGRES_URL not set - configuration endpoints will not work")
            app.state.database_url = None
            service_status.set_status("error")
            raise ValueError("Database URL not configured")

        # Initialize R2 Storage
        global r2_storage
        r2_url = os.getenv("R2_CONNECTION_URL")
        if not r2_url:
            # Construct from individual vars if available
            r2_key = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID")
            r2_secret = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
            r2_account = os.getenv("CLOUDFLARE_R2_ACCOUNT_ID")
            r2_bucket = os.getenv("CLOUDFLARE_R2_BUCKET_NAME")
            r2_public = os.getenv("CLOUDFLARE_R2_PUBLIC_URL")
            if all([r2_key, r2_secret, r2_account, r2_bucket]):
                r2_url = f"r2://{r2_key}:{r2_secret}@{r2_account}/{r2_bucket}"
                if r2_public:
                    r2_url += f"?public_url={r2_public}"
        
        if r2_url:
            try:
                r2_storage = R2Storage(r2_url)
                logger.info("✅ R2 storage initialized")
            except Exception as e:
                logger.error(f"❌ Failed to initialize R2 storage: {e}")

        # Initialize Firebase Auth and Firestore
        try:
            from shared.firebase_auth import init_firebase_auth
            init_firebase_auth()
            logger.info("✅ Firebase Auth and Firestore initialized")
        except Exception as e:
            logger.warning(f"⚠️ Firebase Auth/Firestore not initialized: {e}")
            logger.warning("Authentication endpoints will not work without Firebase")

        service_status.set_status("running")
        logger.info(f"🚀 Configuration service started successfully on port {PORT}")
        yield

        # Shutdown
        service_status.set_status("stopping")
        await close_databases()
        logger.info("✅ Configuration service shutdown complete")
    except Exception as e:
        service_status.set_status("error")
        logger.error(f"❌ Error in lifespan handler: {e}")
        raise

# Create FastAPI app
app = FastAPI(
    title="Configuration Service",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# COOP/COEP headers middleware to fix Cross-Origin-Opener-Policy issues
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to prevent COOP/COEP issues with popup windows."""
    response = await call_next(request)
    
    # Set COOP and COEP headers to allow popup operations without restrictions
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
    
    return response

# Pydantic Models
class NotificationsUpdate(BaseModel):
    user_interactions_enabled: bool
    error_alerts_enabled: bool
    feedback_requests_enabled: bool

class SecurityUpdate(BaseModel):
    response_timeout: int = Field(..., ge=15, le=300, description="Response timeout in seconds (15-300)")
    remove_pii: bool
    restrict_config: bool

    @validator('response_timeout')
    def validate_timeout(cls, v):
        if v < 15 or v > 300:
            raise ValueError('Response timeout must be between 15 and 300 seconds')
        return v

class DataManagementUpdate(BaseModel):
    backup_logs: bool

class PersonaUpdate(BaseModel):
    system_prompt: str = Field(..., min_length=10, max_length=5000)
    selected_persona: str = Field(..., min_length=1, max_length=50)

    @validator('system_prompt')
    def validate_system_prompt(cls, v):
        if not v or not v.strip():
            raise ValueError('System prompt cannot be empty')

        v = v.strip()

        # Check for potentially harmful content
        harmful_patterns = [
            r'ignore.*previous.*instructions',
            r'bypass.*security',
            r'override.*restrictions',
            r'jailbreak',
            r'override.*safety',
            r'forget.*training',
            r'do.*not.*follow.*rules'
        ]

        for pattern in harmful_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError('System prompt contains potentially harmful content')

        # Check for excessive special characters
        special_chars = re.findall(r'[!@#$%^&*()_+=\[\]{}|;:,.<>?]', v)
        if len(special_chars) > len(v) * 0.3:  # More than 30% special chars
            raise ValueError('System prompt contains too many special characters')

        return v

    @validator('selected_persona')
    def validate_persona(cls, v):
        valid_personas = [
            'friendly-receptionist', 'knowledgeable-expert',
            'fast-paced-solver', 'upselling-assistant', 'custom'
        ]
        if v not in valid_personas:
            raise ValueError(f'Invalid persona. Must be one of: {", ".join(valid_personas)}')
        return v

class ValidatedEmail(str):
    """Custom email validator with enhanced checks"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate_email

    @classmethod
    def validate_email(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError('Email is required')

        v = v.strip()

        # Use email_validator for comprehensive email validation
        try:
            # This checks format, MX records, and more
            validate_email(v, check_deliverability=True)
        except EmailNotValidError as e:
            raise ValueError(f'Invalid email: {str(e)}')

        # Additional custom checks
        domain = v.split('@')[1].lower()

        # Block disposable email domains
        disposable_domains = {
            '10minutemail.com', 'temp-mail.org', 'guerrillamail.com',
            'mailinator.com', 'throwaway.email', 'yopmail.com'
        }
        if domain in disposable_domains:
            raise ValueError('Disposable email addresses not allowed')

        # Block common typos
        suspicious_domains = ['gmial.com', 'gmai.com', 'hotmai.com']
        if domain in suspicious_domains:
            raise ValueError('Please check email domain for typos')

        # Check that domain doesn't end with a number (common pattern for temp emails)
        domain_parts = domain.split('.')
        primary_domain = domain_parts[0]
        if primary_domain and primary_domain[-1].isdigit():
            raise ValueError('Domain ending with numbers not allowed')

        # Additional domain validation - check for suspicious patterns
        import re
        suspicious_patterns = [
            r'^[a-z]+\d{2,}$',  # domain with numbers at end like gmail123
            r'^temp',  # starts with temp
            r'^test',  # starts with test
            r'^spam',  # starts with spam
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, primary_domain, re.IGNORECASE):
                raise ValueError('Invalid domain pattern detected')

        return v

class AdminAccount(BaseModel):
    email: ValidatedEmail
    password: str = Field(..., min_length=8, max_length=128)

    @validator('password')
    def validate_password(cls, v):
        if not v:
            raise ValueError('Password is required')

        # Check password strength
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')

        # Must contain at least one uppercase, lowercase, and digit
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')

        return v

class ChatbotConfigRequest(BaseModel):
    admin_emails: Optional[List[Union[ValidatedEmail, AdminAccount]]] = Field(None, max_items=10)
    human_agents: Optional[List[ValidatedEmail]] = Field(None, max_items=20)
    hil_enabled: Optional[bool] = None
    notifications: Optional[NotificationsUpdate] = None
    security: Optional[SecurityUpdate] = None
    response_policy: Optional[int] = Field(None, ge=0, le=100)
    data_management: Optional[DataManagementUpdate] = None
    persona: Optional[PersonaUpdate] = None
    llm_tokens: Optional[dict] = None

    @validator('admin_emails')
    def validate_admin_emails(cls, v):
        if v is not None:
            if len(v) > 10:
                raise ValueError('Maximum 10 admin emails allowed')

            # Check for duplicates
            emails = []
            for item in v:
                if isinstance(item, str):
                    emails.append(item)
                elif hasattr(item, 'email'):
                    emails.append(item.email)

            if len(emails) != len(set(emails)):
                raise ValueError('Duplicate admin emails are not allowed')

        return v

    @validator('human_agents')
    def validate_human_agents(cls, v):
        if v is not None:
            if len(v) > 20:
                raise ValueError('Maximum 20 human agents allowed')

            # Check for duplicates
            if len(v) != len(set(v)):
                raise ValueError('Duplicate human agent emails are not allowed')

        return v


    class Config:
        # Enable validation of assignment
        validate_assignment = True
        # Custom error messages
        error_msg_templates = {
            'value_error.const': 'Invalid value for field',
            'value_error.missing': 'This field is required',
        }

# Position field validation model
class PositionData(BaseModel):
    x: int = 0
    y: int = 0

    def __init__(self, **data):
        super().__init__(**data)
        # Validate coordinates are reasonable
        for coord in ['x', 'y']:
            value = getattr(self, coord)
            if not isinstance(value, int):
                raise ValueError(f'{coord} must be an integer')
            if abs(value) > 10000:  # Reasonable bounds
                raise ValueError(f'{coord} value is too large')

class WidgetConfigRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=50)
    initial_message: Optional[str] = Field(None, min_length=5, max_length=200)
    auto_show_duration: Optional[int] = Field(None, ge=0, le=30)
    suggested_messages: Optional[List[str]] = Field(None, max_items=5)
    keep_showing_suggested: Optional[bool] = None
    theme: Optional[str] = Field(None, pattern=r'^(light|dark)$')
    primary_color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    use_primary_for_header: Optional[bool] = None
    chat_bubble_color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    align_bubble: Optional[str] = Field(None, pattern=r'^(left|right)$')
    display_chatbot: Optional[bool] = None
    profile_picture_url: Optional[str] = None
    chat_icon_url: Optional[str] = None
    # NEW FIELDS - Add zoom and position fields with proper validation
    profile_zoom: Optional[float] = Field(None, ge=0.1, le=5.0)
    chat_icon_zoom: Optional[float] = Field(None, ge=0.1, le=5.0)
    profile_position: Optional[PositionData] = None
    chat_icon_position: Optional[PositionData] = None
    # NEW FIELDS - Add filename fields for displaying original filenames
    profile_picture_filename: Optional[str] = Field(None, max_length=255)
    chat_icon_filename: Optional[str] = Field(None, max_length=255)

    @validator('display_name')
    def validate_display_name(cls, v):
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Display name must be at least 2 characters')
            if len(v) > 50:
                raise ValueError('Display name must be less than 50 characters')

            # Check for inappropriate content
            inappropriate_words = ['spam', 'scam', 'fake', 'test', 'admin', 'root', 'system']
            lower_name = v.lower()
            for word in inappropriate_words:
                if word in lower_name:
                    raise ValueError('Display name contains inappropriate content')

            # Check for excessive special characters
            special_chars = re.findall(r'[!@#$%^&*()_+=\[\]{}|;:,.<>?]', v)
            if len(special_chars) > len(v) * 0.4:  # More than 40% special chars
                raise ValueError('Display name contains too many special characters')

        return v

    @validator('suggested_messages')
    def validate_suggested_messages(cls, v):
        if v:
            for i, message in enumerate(v):
                if message:
                    message = message.strip()
                    if len(message) > 100:
                        raise ValueError(f'Suggested message {i+1} must be less than 100 characters')
                    if len(message) < 1:
                        raise ValueError(f'Suggested message {i+1} cannot be empty')
                    v[i] = message

        return v

    @validator('profile_picture_url', 'chat_icon_url')
    def validate_image_url(cls, v):
        if v:
            # Validate URL format
            url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
            if not re.match(url_pattern, v):
                raise ValueError('Invalid image URL format')

            # Check for allowed image extensions
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            if not any(v.lower().endswith(ext) for ext in allowed_extensions):
                raise ValueError('Image URL must point to a valid image file')

            # Check URL length
            if len(v) > 2048:
                raise ValueError('Image URL is too long')

        return v

    @validator('profile_picture_filename', 'chat_icon_filename')
    def validate_filename(cls, v):
        if v:
            # Basic filename validation
            if len(v) > 255:
                raise ValueError('Filename is too long')

            # Check for dangerous characters
            dangerous_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
            if any(char in v for char in dangerous_chars):
                raise ValueError('Filename contains invalid characters')

        return v

    class Config:
        validate_assignment = True


# Business logic validation function
def validate_configuration_consistency(config: ChatbotConfigRequest):
    """Validate that configuration settings are consistent with business rules"""
    errors = []

    # If HIL is enabled, ensure there are human agents
    if config.hil_enabled and (not config.human_agents or len(config.human_agents) == 0):
        errors.append("Human-in-the-Loop is enabled but no human agents are configured")

    # If HIL is disabled, warn about removing agents
    if config.hil_enabled is False and config.human_agents and len(config.human_agents) > 0:
        errors.append("Human-in-the-Loop is disabled but human agents are still configured")

    # Validate admin email domains (optional business rule)
    if config.admin_emails:
        allowed_domains = ['company.com', 'trusted-domain.org']  # Configure as needed
        for email in config.admin_emails:
            if isinstance(email, str):
                try:
                    domain = email.split('@')[1].lower()
                    if domain not in allowed_domains:
                        errors.append(f"Admin email domain '{domain}' is not in allowed domains")
                except IndexError:
                    pass

    return errors


@asynccontextmanager
async def get_db_connection():
    """
    Get database connection using the pre-initialized connection pool.
    
    The database pool is initialized during service startup for optimal performance.
    """
    try:
        # Use the pre-initialized DatabaseConnection context manager
        from shared.db import DatabaseConnection
        async with DatabaseConnection() as conn:
            yield conn

    except RuntimeError as e:
        error_msg = str(e)
        if "returned None" in error_msg:
            logger.error("❌ Database connection pool returned None - this indicates pool corruption")
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable due to connection pool corruption. Please try again."
            )
        elif "timed out" in error_msg:
            logger.error("❌ Database connection acquisition timed out")
            raise HTTPException(
                status_code=503,
                detail="Database connection timeout. Please try again."
            )
        elif "unhealthy" in error_msg:
            logger.error("❌ Database pool health check failed")
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable. Please try again."
            )
        else:
            logger.error(f"❌ Database runtime error: {e}")
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable"
            )

    except asyncpg_exceptions.TooManyConnectionsError:
        logger.error("❌ Database connection pool exhausted")
        raise HTTPException(
            status_code=503,
            detail="Database connection pool exhausted. Please try again in a few moments."
        )

    except Exception as e:
        error_msg = str(e)
        # Handle specific database errors
        if "too many clients already" in error_msg.lower():
            logger.error(f"❌ Railway PostgreSQL connection limit exceeded: {e}")
            raise HTTPException(
                status_code=503,
                detail="Database connection limit exceeded. Please wait and retry."
            )
        elif "connection timed out" in error_msg.lower() or "connection timeout" in error_msg.lower():
            logger.error(f"❌ Database connection timeout: {e}")
            raise HTTPException(
                status_code=503,
                detail="Database connection timeout. Please try again."
            )
        elif "authentication failed" in error_msg.lower():
            logger.error(f"❌ Database authentication failed")
            raise HTTPException(
                status_code=503,
                detail="Database authentication error. Please contact support."
            )
        else:
            logger.error(f"❌ Unexpected error in get_db_connection: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="Database service temporarily unavailable"
            )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint with enhanced database pool monitoring"""
    db_status = "disconnected"
    pool_stats = None
    tables_status = {}

    if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
        db_status = "connected"
        try:
            # Check if required tables exist
            async with railway_db.acquire() as conn:
                required_tables = [
                    'widget_configuration',
                    'widget_suggested_messages',
                    'configuration_metadata',
                    'notification_settings',
                    'security_settings',
                    'llm_providers',
                    'persona_configurations',
                    'admins',
                    'human_agents'
                ]
                
                for table in required_tables:
                    exists = await conn.fetchval(
                        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = $1)",
                        table
                    )
                    tables_status[table] = exists
                
                # Only mark as healthy if all required tables exist
                all_tables_exist = all(tables_status.values())
                db_status = "healthy" if all_tables_exist else "missing_tables"
                
        except Exception as e:
            db_status = f"error: {str(e)[:100]}"  # Truncate error message
            logger.warning(f"Database health check failed: {e}")

    # Get overall service status
    service_info = service_status.get_status()
    service_info.update({
        "database": db_status,
        "tables": tables_status,
        "pool_stats": pool_stats,
        "timestamp": "2026-01-13T07:34:00Z"  # Current date
    })

    return service_info


# Chatbot Configuration Endpoints

@app.get("/api/v1/configuration/chatbot")
async def get_chatbot_config():
    """Get chatbot configuration"""
    from fastapi.responses import JSONResponse

    try:
        async with get_db_connection() as conn:
            # Read from new normalized tables
            # Get configuration metadata
            metadata = await conn.fetchrow(
                """
                SELECT default_user_role, hil_enabled, response_policy
                FROM configuration_metadata
                WHERE id = 1
                """
            )

            # Get notification settings
            notification_rows = await conn.fetch(
                """
                SELECT setting_name, is_enabled
                FROM notification_settings
                ORDER BY setting_name
                """
            )

            # Get security settings
            security_rows = await conn.fetch(
                """
                SELECT setting_name, setting_value, setting_type
                FROM security_settings
                ORDER BY setting_name
                """
            )

            # Get LLM providers
            llm_rows = await conn.fetch(
                """
                SELECT provider_name, token_limit, token_used
                FROM llm_providers
                WHERE is_active = true
                ORDER BY provider_name
                """
            )

            # Get active persona
            persona = await conn.fetchrow(
                """
                SELECT persona_name, system_prompt
                FROM persona_configurations
                WHERE is_active = true
                LIMIT 1
                """
            )

            # Fetch human agents from the human_agents table (status removed)
            human_agents_rows = await conn.fetch(
                """
                SELECT email FROM human_agents
                ORDER BY email
                """
            )
            human_agents_list = [agent["email"] for agent in human_agents_rows] if human_agents_rows else []
            logger.info(f"Fetched {len(human_agents_list)} human agent(s) from human_agents table: {human_agents_list}")

            # Fetch admins from the admins table
            admin_rows = await conn.fetch(
                """
                SELECT email FROM admins
                ORDER BY email
                """
            )
            admin_emails_list = [admin["email"] for admin in admin_rows] if admin_rows else []
            logger.info(f"Fetched {len(admin_emails_list)} admin(s) from admins table: {admin_emails_list}")

            # Build notification settings dict
            notifications = {
                "user_interactions_enabled": False,
                "error_alerts_enabled": False,
                "feedback_requests_enabled": True
            }
            for row in notification_rows:
                if row['setting_name'] == 'user_interactions_enabled':
                    notifications['user_interactions_enabled'] = row['is_enabled']
                elif row['setting_name'] == 'error_alerts_enabled':
                    notifications['error_alerts_enabled'] = row['is_enabled']
                elif row['setting_name'] == 'feedback_requests_enabled':
                    notifications['feedback_requests_enabled'] = row['is_enabled']

            # Build security settings dict
            security = {
                "response_timeout": 30,
                "remove_pii": False,
                "restrict_config": False
            }
            for row in security_rows:
                if row['setting_name'] == 'response_timeout':
                    security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30
                elif row['setting_name'] == 'remove_pii':
                    security['remove_pii'] = row['setting_value'].lower() == 'true' if row['setting_type'] == 'boolean' else False
                elif row['setting_name'] == 'restrict_config':
                    security['restrict_config'] = row['setting_value'].lower() == 'true' if row['setting_type'] == 'boolean' else False

            # Build LLM tokens dict
            llm_tokens = {
                "gemini": {"used": 0, "available": 20000, "limit": 20000}
            }
            for row in llm_rows:
                provider = row['provider_name']
                if provider == 'gemini':
                    llm_tokens['gemini'] = {
                        "used": row['token_used'] or 0,
                        "available": (row['token_limit'] or 0) - (row['token_used'] or 0),
                        "limit": row['token_limit'] or 0
                    }

            # Build persona dict
            persona_config = {
                "system_prompt": persona['system_prompt'] if persona else "",
                "selected_persona": persona['persona_name'] if persona else "friendly-receptionist"
            }

            # Build final configuration
            data = {
                "admin_user": "GLOBISTAAN",
                "admin_emails": admin_emails_list,
                "admin_password": "**********",
                "human_agents": human_agents_list,
                "hil_enabled": metadata['hil_enabled'] if metadata else True,
                "notifications": notifications,
                "security": security,
                "response_policy": metadata['response_policy'] if metadata else 30,
                "data_management": {
                    "backup_logs": False  # This was removed from old schema, keeping default
                },
                "persona": persona_config,
                "llm_tokens": llm_tokens
            }
            response = JSONResponse(content=data)
            # Add cache headers for faster loading (5 seconds cache, but allow revalidation)
            response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
            return response
    except Exception as e:
        logger.error(f"Error fetching chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching configuration: {str(e)}")


@app.post("/api/v1/configuration/chatbot")
async def save_chatbot_config(
    config: ChatbotConfigRequest,
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Save chatbot configuration"""
    try:
        # Validate business logic
        business_errors = validate_configuration_consistency(config)
        if business_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Business logic validation failed: {'; '.join(business_errors)}"
            )

        async with get_db_connection() as conn:
            # Handle admin emails (add to admins table directly - Google auth only)
            if config.admin_emails is not None:
                for admin_item in config.admin_emails:
                    # Handle both dict (AdminAccount) and str formats
                    if isinstance(admin_item, dict):
                        email = admin_item.get('email', '')
                        if email:
                            try:
                                # Add to admins table directly (no Firebase account needed for Google auth)
                                await conn.execute(
                                    """
                                    INSERT INTO admins (email)
                                    VALUES ($1)
                                    ON CONFLICT (email)
                                    DO NOTHING
                                    """,
                                    email
                                )
                                logger.info(f"Admin {email} added to database")
                            except Exception as e:
                                logger.error(f"Error adding admin {email}: {e}")
                    elif hasattr(admin_item, 'email'):
                        email = admin_item.email
                        if email:
                            try:
                                await conn.execute(
                                    """
                                    INSERT INTO admins (email)
                                    VALUES ($1)
                                    ON CONFLICT (email)
                                    DO NOTHING
                                    """,
                                    email
                                )
                                logger.info(f"Admin {email} added to database")
                            except Exception as e:
                                logger.error(f"Error adding admin {email}: {e}")
                    elif isinstance(admin_item, str):
                        try:
                            await conn.execute(
                                """
                                INSERT INTO admins (email)
                                VALUES ($1)
                                ON CONFLICT (email)
                                DO NOTHING
                                """,
                                admin_item
                            )
                            logger.info(f"Admin {admin_item} added to database")
                        except Exception as e:
                            logger.error(f"Error adding admin {admin_item}: {e}")

            # Handle human agents (add to human_agents table)
            if config.human_agents is not None:
                # Process human agents - they should be email addresses
                for agent_email in config.human_agents:
                    if agent_email and isinstance(agent_email, str):
                        try:
                            # Check if human agent already exists
                            existing_agent = await conn.fetchrow(
                                "SELECT id FROM human_agents WHERE email = $1",
                                agent_email
                            )
                            if not existing_agent:
                                # Create new human agent (no Firebase account needed)

                                # Add to human_agents table directly (no status needed)
                                await conn.execute(
                                    """
                                    INSERT INTO human_agents (email)
                                    VALUES ($1)
                                    ON CONFLICT (email)
                                    DO NOTHING
                                    """,
                                    agent_email
                                )
                                logger.info(f"Human agent {agent_email} added directly")

                        except Exception as e:
                            logger.error(f"Error processing human agent {agent_email}: {e}")

            # Update configuration metadata
            if any([config.hil_enabled is not None, config.response_policy is not None]):
                updates = []
                values = []
                param_index = 1

                if config.hil_enabled is not None:
                    updates.append(f"hil_enabled = ${param_index}")
                    values.append(config.hil_enabled)
                    param_index += 1

                if config.response_policy is not None:
                    updates.append(f"response_policy = ${param_index}")
                    values.append(config.response_policy)
                    param_index += 1


                if updates:
                    query = f"""
                    INSERT INTO configuration_metadata (id, {', '.join(field.split(' = ')[0] for field in updates)})
                    VALUES (1, {', '.join('$' + str(i) for i in range(1, param_index))})
                    ON CONFLICT (id) DO UPDATE SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
                    """
                    await conn.execute(query, *values)

            # Update notification settings
            if config.notifications:
                if config.notifications.user_interactions_enabled is not None:
                    await conn.execute(
                        """
                        INSERT INTO notification_settings (setting_name, is_enabled, description)
                        VALUES ('user_interactions_enabled', $1, 'Enable notifications for user interactions')
                        ON CONFLICT (setting_name) DO UPDATE SET is_enabled = $1
                        """,
                        config.notifications.user_interactions_enabled
                    )

                if config.notifications.error_alerts_enabled is not None:
                    await conn.execute(
                        """
                        INSERT INTO notification_settings (setting_name, is_enabled, description)
                        VALUES ('error_alerts_enabled', $1, 'Enable error alert notifications')
                        ON CONFLICT (setting_name) DO UPDATE SET is_enabled = $1
                        """,
                        config.notifications.error_alerts_enabled
                    )

                if config.notifications.feedback_requests_enabled is not None:
                    await conn.execute(
                        """
                        INSERT INTO notification_settings (setting_name, is_enabled, description)
                        VALUES ('feedback_requests_enabled', $1, 'Enable feedback request notifications')
                        ON CONFLICT (setting_name) DO UPDATE SET is_enabled = $1
                        """,
                        config.notifications.feedback_requests_enabled
                    )

            # Update security settings
            if config.security:
                if config.security.response_timeout is not None:
                    await conn.execute(
                        """
                        INSERT INTO security_settings (setting_name, setting_value, setting_type, description)
                        VALUES ('response_timeout', $1, 'integer', 'Response timeout in seconds')
                        ON CONFLICT (setting_name) DO UPDATE SET setting_value = $1
                        """,
                        str(config.security.response_timeout)
                    )

                if config.security.remove_pii is not None:
                    await conn.execute(
                        """
                        INSERT INTO security_settings (setting_name, setting_value, setting_type, description)
                        VALUES ('remove_pii', $1, 'boolean', 'Remove personally identifiable information')
                        ON CONFLICT (setting_name) DO UPDATE SET setting_value = $1
                        """,
                        str(config.security.remove_pii).lower()
                    )

                if config.security.restrict_config is not None:
                    await conn.execute(
                        """
                        INSERT INTO security_settings (setting_name, setting_value, setting_type, description)
                        VALUES ('restrict_config', $1, 'boolean', 'Restrict configuration access')
                        ON CONFLICT (setting_name) DO UPDATE SET setting_value = $1
                        """,
                        str(config.security.restrict_config).lower()
                    )

            # Update persona configuration
            if config.persona:
                if config.persona.selected_persona and config.persona.system_prompt:
                    # First, set all personas to inactive
                    await conn.execute("UPDATE persona_configurations SET is_active = false")

                    # Then insert/update the active persona
                    await conn.execute(
                        """
                        INSERT INTO persona_configurations (persona_name, system_prompt, is_active)
                        VALUES ($1, $2, true)
                        ON CONFLICT (persona_name) DO UPDATE SET
                            system_prompt = $2,
                            is_active = true
                        """,
                        config.persona.selected_persona,
                        config.persona.system_prompt
                    )

            # Update LLM provider configurations
            if config.llm_tokens:
                if "gemini" in config.llm_tokens:
                    token_limit = config.llm_tokens["gemini"].get("limit")
                    token_used = config.llm_tokens["gemini"].get("used")
                    if token_limit is not None:
                        await conn.execute(
                            """
                            INSERT INTO llm_providers (provider_name, token_limit, is_active)
                            VALUES ('gemini', $1, true)
                            ON CONFLICT (provider_name) DO UPDATE SET token_limit = $1
                            """,
                            token_limit
                        )
                    if token_used is not None:
                        await conn.execute(
                            "UPDATE llm_providers SET token_used = $1 WHERE provider_name = 'gemini'",
                            token_used
                        )

                if "deepseek" in config.llm_tokens:
                    token_limit = config.llm_tokens["deepseek"].get("limit")
                    token_used = config.llm_tokens["deepseek"].get("used")
                    if token_limit is not None:
                        await conn.execute(
                            """
                            INSERT INTO llm_providers (provider_name, token_limit, is_active)
                            VALUES ('deepseek', $1, true)
                            ON CONFLICT (provider_name) DO UPDATE SET token_limit = $1
                            """,
                            token_limit
                        )
                    if token_used is not None:
                        await conn.execute(
                            "UPDATE llm_providers SET token_used = $1 WHERE provider_name = 'deepseek'",
                            token_used
                        )
            
            # Configuration updates completed using normalized tables
            logger.info("Configuration saved successfully using normalized tables")
            
            # If human agents are provided, trigger email sending
            logger.info(f"Checking human agents: config.human_agents = {config.human_agents}")
            if config.human_agents is not None and len(config.human_agents) > 0:
                logger.info(f"Processing {len(config.human_agents)} human agent(s) for email sending")
                try:
                    # Import email service and helper functions
                    from shared.email_service import create_email_service
                    from services.configuration_service.human_agents import (
                        generate_confirmation_token,
                        generate_confirmation_link
                    )
                    
                    logger.info("Email service imports successful, creating email service instance")
                    # Create email service with database connection
                    email_service = create_email_service(conn)
                    agents_emailed = []
                    
                    logger.info(f"Starting email sending loop for {len(config.human_agents)} agent(s)")
                    for email in config.human_agents:
                        if not email or not email.strip():
                            continue
                        
                        email = email.strip()
                        
                        # Check if agent already exists
                        existing = await conn.fetchrow(
                            "SELECT id FROM human_agents WHERE email = $1",
                            email
                        )

                        if existing:
                            logger.info(f"Agent {email} already exists, skipping creation")
                            continue

                        # Create new agent (no email/password needed)
                        logger.info(f"Creating new agent record for {email}")
                        agent_id = await conn.fetchval(
                            """
                            INSERT INTO human_agents (email)
                            VALUES ($1)
                            RETURNING id::text
                            """,
                            email
                        )

                        agents_created.append({
                            "email": email
                        })
                        logger.info(f"✅ Human agent {email} added directly")
                except Exception as e:
                    # Don't fail the entire save if email sending fails
                    logger.error(f"❌ Error sending human agent emails: {e}", exc_info=True)
                    logger.error(f"Error type: {type(e).__name__}")
            
            # Handle deletion of agents that are no longer in the list
            if config.human_agents is not None:
                try:
                    # Get all current agents from the database
                    current_agents = await conn.fetch(
                        "SELECT email FROM human_agents"
                    )
                    
                    # Create a mapping of lowercase email to original email for comparison
                    current_emails_map = {agent['email'].lower(): agent['email'] for agent in current_agents}
                    
                    # Get the new list of emails (normalize to lowercase for comparison)
                    new_emails_lower = {email.strip().lower() for email in config.human_agents if email and email.strip()}
                    
                    # Find agents to delete (in database but not in new list)
                    agents_to_delete = []
                    for lower_email, original_email in current_emails_map.items():
                        if lower_email not in new_emails_lower:
                            agents_to_delete.append(original_email)
                    
                    # Delete agents that are no longer in the list
                    if agents_to_delete:
                        logger.info(f"Deleting {len(agents_to_delete)} agent(s) that are no longer in the list: {', '.join(agents_to_delete)}")
                        for email in agents_to_delete:
                            await conn.execute(
                                "DELETE FROM human_agents WHERE email = $1",
                                email
                            )
                            logger.info(f"✅ Deleted agent {email} from database")
                    else:
                        logger.info("No agents to delete - all current agents are in the new list")
                except Exception as e:
                    # Don't fail the entire save if deletion fails
                    logger.error(f"❌ Error deleting removed human agents: {e}", exc_info=True)
            else:
                logger.info("No human agents provided or list is empty, skipping email sending and deletion")

            # Log the configuration change (non-blocking)
            try:
                await log_configuration_change(
                    user_email=current_user.get('email'),
                    action='chatbot_config_update',
                    details=config.dict(exclude_unset=True),
                    ip_address=request.client.host if request else None
                )
            except Exception as e:
                logger.warning(f"Failed to log configuration change: {e}")
                # Don't fail the configuration save if logging fails

            return {"success": True, "message": "Configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving configuration: {str(e)}")


@app.post("/api/v1/widget/upload-image")
async def upload_widget_image(
    file: UploadFile = File(...),
    type: str = Form(...),  # 'profile', 'chatIcon', or 'headerIcon'
    current_user: dict = Depends(get_current_user)
):
    """Upload widget related images (profile, chat icon, header icon) to R2 storage."""
    if not r2_storage:
        raise HTTPException(status_code=503, detail="R2 storage not configured")

    if type not in ['profile', 'chatIcon', 'headerIcon']:
        raise HTTPException(status_code=400, detail="Invalid image type. Must be 'profile', 'chatIcon', or 'headerIcon'")

    # Validate file type
    allowed_content_types = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
    if file.content_type not in allowed_content_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Only JPEG, PNG, WEBP, and GIF are allowed.")

    # Validate file size (max 2MB)
    MAX_SIZE = 2 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 2MB.")
    
    # Reset file cursor for further reading if needed (not needed for small files read into memory)
    
    try:
        # Create a temp file to upload
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename or "")[1]) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Upload to R2
            prefix = f"widget/{type}"
            result = await r2_storage.upload_file(
                file_path=tmp_path,
                content_type=file.content_type,
                metadata={'original_filename': file.filename or "unknown", 'user': current_user.get('email', 'unknown')}
            )
            
            if not result or not result.get('url'):
                # Fallback path if public_url is not configured
                # In a real system, we'd provide a proxy URL through our API
                raise HTTPException(status_code=500, detail="Failed to generate public URL for uploaded file")

            logger.info(f"Successfully uploaded {type} image: {result['url']}")
            return {
                "url": result['url'],
                "filename": file.filename
            }
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    except Exception as e:
        logger.error(f"Error uploading image to R2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")


# Widget Configuration Endpoints
@app.get("/api/v1/configuration/widget")
async def get_widget_config():
    """Get widget configuration"""
    from fastapi.responses import JSONResponse

    try:
        async with get_db_connection() as conn:
            # Get main widget configuration with defensive column selection
            try:
                row = await conn.fetchrow(
                    """
                    SELECT
                        display_name,
                        initial_message,
                        auto_show_duration,
                        keep_showing_suggested,
                        theme,
                        primary_color,
                        use_primary_for_header,
                        chat_bubble_color,
                        align_bubble,
                        display_chatbot,
                        profile_picture_url,
                        chat_icon_url,
                        profile_zoom,
                        chat_icon_zoom,
                        profile_position,
                        chat_icon_position,
                        profile_picture_filename,
                        chat_icon_filename,
                        updated_at
                    FROM widget_configuration
                    WHERE id = 1
                    """
                )
            except asyncpg.exceptions.UndefinedColumnError as e:
                # If columns don't exist, try with more defensive query
                logger.warning(f"Some columns missing, trying fallback query: {e}")
                row = await conn.fetchrow(
                    """
                    SELECT
                        display_name,
                        initial_message,
                        auto_show_duration,
                        keep_showing_suggested,
                        theme,
                        primary_color,
                        use_primary_for_header,
                        chat_bubble_color,
                        align_bubble,
                        display_chatbot,
                        profile_picture_url,
                        chat_icon_url,
                        updated_at
                    FROM widget_configuration
                    WHERE id = 1
                    """
                )

            # Get suggested messages from normalized table
            suggested_messages_rows = await conn.fetch(
                """
                SELECT message_text
                FROM widget_suggested_messages
                WHERE widget_config_id = 1 AND is_active = true
                ORDER BY display_order
                """
            )
            suggested_messages = [row["message_text"] for row in suggested_messages_rows] if suggested_messages_rows else []

            if not row:
                # Return default configuration with cache headers
                data = {
                    "display_name": "GLOBISTAAN",
                    "initial_message": "Hi! What can I help you with?",
                    "auto_show_duration": 4,
                    "suggested_messages": [],
                    "keep_showing_suggested": True,
                    "theme": "light",
                    "primary_color": "#3B81F6",
                    "use_primary_for_header": True,
                    "chat_bubble_color": "#3B81F6",
                    "align_bubble": "right",
                    "display_chatbot": True,
                    "profile_picture_url": None,
                    "chat_icon_url": None,
                    "profile_zoom": 1.0,
                    "chat_icon_zoom": 1.0,
                    "profile_position": {"x": 0, "y": 0},
                    "chat_icon_position": {"x": 0, "y": 0}
                }
                response = JSONResponse(content=data)
                response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
                return response

            # Build data object defensively based on available columns
            data = {
                "display_name": row["display_name"],
                "initial_message": row["initial_message"],
                "auto_show_duration": row["auto_show_duration"],
                "suggested_messages": suggested_messages,
                "keep_showing_suggested": row["keep_showing_suggested"],
                "theme": row["theme"],
                "primary_color": row["primary_color"],
                "use_primary_for_header": row["use_primary_for_header"],
                "chat_bubble_color": row["chat_bubble_color"],
                "align_bubble": row["align_bubble"],
                "display_chatbot": row["display_chatbot"] if row["display_chatbot"] is not None else True,
                "profile_picture_url": row["profile_picture_url"],
                "chat_icon_url": row["chat_icon_url"],
            }
            
            # Add optional fields if they exist in the row
            if "profile_zoom" in row and row["profile_zoom"] is not None:
                data["profile_zoom"] = float(row["profile_zoom"])
            else:
                data["profile_zoom"] = 1.0
                
            if "chat_icon_zoom" in row and row["chat_icon_zoom"] is not None:
                data["chat_icon_zoom"] = float(row["chat_icon_zoom"])
            else:
                data["chat_icon_zoom"] = 1.0
                
            if "profile_position" in row and row["profile_position"] is not None and isinstance(row["profile_position"], dict):
                data["profile_position"] = row["profile_position"]
            else:
                data["profile_position"] = {"x": 0, "y": 0}
                
            if "chat_icon_position" in row and row["chat_icon_position"] is not None and isinstance(row["chat_icon_position"], dict):
                data["chat_icon_position"] = row["chat_icon_position"]
            else:
                data["chat_icon_position"] = {"x": 0, "y": 0}
                
            if "profile_picture_filename" in row:
                data["profile_picture_filename"] = row.get("profile_picture_filename")
                
            if "chat_icon_filename" in row:
                data["chat_icon_filename"] = row.get("chat_icon_filename")
            response = JSONResponse(content=data)
            response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
            return response
    except Exception as e:
        logger.error(f"Error fetching widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching widget configuration: {str(e)}")


@app.post("/api/v1/configuration/widget")
async def save_widget_config(
    config: WidgetConfigRequest,
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Save widget configuration"""
    try:
        async with get_db_connection() as conn:
            # Build update query dynamically for widget_configuration table
            updates = []
            values = []
            param_index = 1

            fields_map = {
                "display_name": "display_name",
                "initial_message": "initial_message",
                "auto_show_duration": "auto_show_duration",
                "keep_showing_suggested": "keep_showing_suggested",
                "theme": "theme",
                "primary_color": "primary_color",
                "use_primary_for_header": "use_primary_for_header",
                "chat_bubble_color": "chat_bubble_color",
                "align_bubble": "align_bubble",
                "display_chatbot": "display_chatbot",
                "profile_picture_url": "profile_picture_url",
                "chat_icon_url": "chat_icon_url",
                # NEW FIELDS - Add zoom and position fields
                "profile_zoom": "profile_zoom",
                "chat_icon_zoom": "chat_icon_zoom",
                "profile_position": "profile_position",
                "chat_icon_position": "chat_icon_position",
                # NEW FIELDS - Add filename fields
                "profile_picture_filename": "profile_picture_filename",
                "chat_icon_filename": "chat_icon_filename"
            }

            for field, db_field in fields_map.items():
                value = getattr(config, field, None)
                if value is not None:
                    # Position fields are now validated by Pydantic as PositionData objects
                    # Convert to JSON string for JSONB storage
                    if field in ['profile_position', 'chat_icon_position']:
                        if hasattr(value, 'dict'):  # Pydantic model
                            value = json.dumps(value.dict())
                        elif isinstance(value, dict):
                            value = json.dumps(value)  # Convert dict to JSON string
                        else:
                            value = json.dumps({"x": 0, "y": 0})  # Fallback as JSON string

                    updates.append(f"{db_field} = ${param_index}")
                    values.append(value)
                    param_index += 1

            # Handle suggested_messages separately - they go to widget_suggested_messages table
            if config.suggested_messages is not None:
                # First, clear existing suggested messages
                await conn.execute("DELETE FROM widget_suggested_messages WHERE widget_config_id = 1")

                # Then insert new ones
                for i, message in enumerate(config.suggested_messages):
                    if message and isinstance(message, str):
                        await conn.execute(
                            """
                            INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active)
                            VALUES (1, $1, $2, true)
                            """,
                            message, i
                        )

            if updates:
                # Use INSERT ... ON CONFLICT to handle upsert for widget_configuration
                existing = await conn.fetchrow("SELECT id FROM widget_configuration LIMIT 1")

                if existing:
                    # Update existing row
                    query = f"""
                        UPDATE widget_configuration
                        SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
                        WHERE id = {existing['id']}
                    """
                else:
                    # Insert new row with id=1
                    query = f"""
                        INSERT INTO widget_configuration (id, {', '.join([u.split(' = ')[0] for u in updates])})
                        VALUES (1, {', '.join([f'${i+1}' for i in range(len(updates))])})
                    """

                await conn.execute(query, *values)

            # Log the configuration change (non-blocking)
            try:
                await log_configuration_change(
                    user_email=current_user.get('email'),
                    action='widget_config_update',
                    details=config.dict(exclude_unset=True),
                    ip_address=request.client.host if request else None
                )
            except Exception as e:
                logger.warning(f"Failed to log widget configuration change: {e}")
                # Don't fail the configuration save if logging fails

            return {"success": True, "message": "Widget configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving widget configuration: {str(e)}")


# Import and include new routers
try:
    from services.configuration_service.human_agents import router as human_agents_router
    from services.configuration_service.feedback import router as feedback_router
    from services.configuration_service.token_usage import router as token_usage_router
    from services.configuration_service.performance import router as performance_router
    from services.configuration_service.admin_management import router as admin_management_router
    from services.configuration_service.auth_optimized import router as auth_router
    from services.configuration_service.chat_log import router as chat_log_router, public_chat_router
    from services.configuration_service.user_ids import router as user_ids_router

    app.include_router(human_agents_router)
    app.include_router(feedback_router)
    app.include_router(token_usage_router)
    app.include_router(admin_management_router)
    app.include_router(auth_router)
    app.include_router(performance_router)
    app.include_router(chat_log_router)
    app.include_router(user_ids_router)
    app.include_router(public_chat_router)  # Public chat endpoints (no auth required)
    logger.info("✅ New endpoints (human agents, feedback, token usage, admin management, auth, chat log) loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ Could not import new endpoint modules: {e}")
    logger.warning("New endpoints (human agents, feedback, token usage, auth, chat log) will not be available")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

