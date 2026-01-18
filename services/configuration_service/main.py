"""
Configuration Service - Handles chatbot and widget configuration management
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union
import os
import logging
import sys
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

load_dotenv()

# Lock for database initialization to prevent race conditions
_db_init_lock = asyncio.Lock()

async def init_database_schema(database_url: str):
    """Initialize database schema if tables don't exist"""
    try:
        conn = await asyncpg.connect(database_url)
        
        # Check if widget_configuration table exists
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
    response_timeout: int
    remove_pii: bool
    restrict_config: bool

class DataManagementUpdate(BaseModel):
    backup_logs: bool

class PersonaUpdate(BaseModel):
    system_prompt: str
    selected_persona: str

class AdminAccount(BaseModel):
    email: str
    password: str

class ChatbotConfigRequest(BaseModel):
    admin_emails: Optional[List[Union[str, AdminAccount]]] = None
    human_agents: Optional[List[str]] = None
    hil_enabled: Optional[bool] = None
    notifications: Optional[NotificationsUpdate] = None
    security: Optional[SecurityUpdate] = None
    response_policy: Optional[int] = None
    data_management: Optional[DataManagementUpdate] = None
    persona: Optional[PersonaUpdate] = None
    llm_tokens: Optional[dict] = None

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
    display_name: Optional[str] = None
    initial_message: Optional[str] = None
    auto_show_duration: Optional[int] = None
    suggested_messages: Optional[List[str]] = None
    keep_showing_suggested: Optional[bool] = None
    theme: Optional[str] = None
    primary_color: Optional[str] = None
    use_primary_for_header: Optional[bool] = None
    chat_bubble_color: Optional[str] = None
    align_bubble: Optional[str] = None
    profile_picture_url: Optional[str] = None
    chat_icon_url: Optional[str] = None
    # NEW FIELDS - Add zoom and position fields with proper validation
    profile_zoom: Optional[float] = None
    chat_icon_zoom: Optional[float] = None
    profile_position: Optional[PositionData] = None
    chat_icon_position: Optional[PositionData] = None
    # NEW FIELDS - Add filename fields for displaying original filenames
    profile_picture_filename: Optional[str] = None
    chat_icon_filename: Optional[str] = None


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

            # Fetch human agents from the human_agents table
            human_agents_rows = await conn.fetch(
                """
                SELECT email FROM human_agents
                WHERE status IN ('confirmed', 'pending')
                ORDER BY email
                """
            )
            human_agents_list = [agent["email"] for agent in human_agents_rows] if human_agents_rows else []
            logger.info(f"Fetched {len(human_agents_list)} human agent(s) from human_agents table: {human_agents_list}")

            # Fetch admins from the admins table
            admin_rows = await conn.fetch(
                """
                SELECT email FROM admins
                WHERE status IN ('confirmed', 'pending')
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
                "gemini": {"used": 0, "available": 20000, "limit": 20000},
                "openai": {"used": 0, "available": 0, "limit": 0}
            }
            for row in llm_rows:
                provider = row['provider_name']
                if provider == 'gemini':
                    llm_tokens['gemini'] = {
                        "used": row['token_used'] or 0,
                        "available": (row['token_limit'] or 0) - (row['token_used'] or 0),
                        "limit": row['token_limit'] or 0
                    }
                elif provider == 'deepseek':
                    llm_tokens['openai'] = {
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
async def save_chatbot_config(config: ChatbotConfigRequest):
    """Save chatbot configuration"""
    try:
        async with get_db_connection() as conn:
            # Handle admin emails (create Firebase accounts and add to admins table)
            if config.admin_emails is not None:
                admin_emails_to_create = []

                for admin_item in config.admin_emails:
                    # Handle both dict (AdminAccount) and str formats
                    if isinstance(admin_item, dict):
                        email = admin_item.get('email', '')
                        if email:
                            admin_emails_to_create.append(email)
                    elif hasattr(admin_item, 'email'):
                        email = admin_item.email
                        if email:
                            admin_emails_to_create.append(email)
                    elif isinstance(admin_item, str):
                        admin_emails_to_create.append(admin_item)

                # Create Firebase accounts for admins with auto-generated passwords
                if admin_emails_to_create:
                    try:
                        from firebase_admin import auth
                        from shared.firebase_auth import init_firebase_auth
                        from services.configuration_service.admin_management import generate_confirmation_token
                        from shared.email_service import create_email_service
                        import secrets

                        init_firebase_auth()
                        email_service = create_email_service(conn)

                        for email in admin_emails_to_create:
                            try:
                                # Check if admin already exists and is confirmed
                                existing_admin = await conn.fetchrow(
                                    "SELECT status FROM admins WHERE email = $1",
                                    email
                                )
                                if existing_admin and existing_admin['status'] == 'confirmed':
                                    logger.info(f"Admin {email} is already confirmed, skipping reset to pending")
                                    continue

                                # Generate a secure random password
                                generated_password = secrets.token_urlsafe(16)

                                # Check if user already exists in Firebase
                                try:
                                    existing_user = auth.get_user_by_email(email)
                                    # User exists, update password with generated one
                                    auth.update_user(existing_user.uid, password=generated_password)
                                    logger.info(f"Updated password for existing Firebase user: {email}")
                                except auth.UserNotFoundError:
                                    # User doesn't exist, create new user with generated password
                                    user = auth.create_user(
                                        email=email,
                                        password=generated_password,
                                        email_verified=False
                                    )
                                    logger.info(f"Created Firebase user: {email} (UID: {user.uid})")

                                # Add to admins table and send verification email with password
                                token = generate_confirmation_token()
                                await conn.execute(
                                    """
                                    INSERT INTO admins (email, status, confirmation_token, auto_generated_password)
                                    VALUES ($1, 'pending', $2, $3)
                                    ON CONFLICT (email)
                                    DO UPDATE SET confirmation_token = $2, status = 'pending', auto_generated_password = $3
                                    """,
                                    email, token, generated_password
                                )

                                # Send verification email with generated password
                                await email_service.send_admin_confirmation_email(email, token, "system", generated_password)
                                logger.info(f"Verification email with password sent to admin: {email}")

                            except Exception as e:
                                logger.error(f"Error creating Firebase account for {email}: {e}", exc_info=True)
                                # Continue with other admins even if one fails
                    except Exception as e:
                        logger.error(f"Error processing admin accounts: {e}", exc_info=True)
                        # Don't fail the whole request if admin creation fails

            # Handle human agents (add to human_agents table)
            if config.human_agents is not None:
                # Process human agents - they should be email addresses
                for agent_email in config.human_agents:
                    if agent_email and isinstance(agent_email, str):
                        try:
                            # Check if human agent already exists
                            existing_agent = await conn.fetchrow(
                                "SELECT status FROM human_agents WHERE email = $1",
                                agent_email
                            )
                            if not existing_agent:
                                # Create new human agent
                                token = generate_confirmation_token()
                                generated_password = secrets.token_urlsafe(16)

                                # Create Firebase user for agent
                                try:
                                    from firebase_admin import auth
                                    from shared.firebase_auth import init_firebase_auth
                                    init_firebase_auth()

                                    # Check if user already exists
                                    try:
                                        existing_user = auth.get_user_by_email(agent_email)
                                        logger.info(f"Firebase user already exists for agent: {agent_email} (UID: {existing_user.uid})")
                                        # User exists, we'll update their password if they haven't confirmed yet
                                        # This handles the case where agent creation was attempted but failed previously
                                        if existing_user.email_verified:
                                            logger.info(f"Agent {agent_email} is already verified, skipping password update")
                                        else:
                                            # Update password for unverified users (allows them to login with new temp password)
                                            auth.update_user(existing_user.uid, password=generated_password)
                                            logger.info(f"Updated password for existing Firebase user: {agent_email}")
                                    except auth.UserNotFoundError:
                                        # User doesn't exist, create new one
                                        user = auth.create_user(
                                            email=agent_email,
                                            password=generated_password,
                                            email_verified=False
                                        )
                                        logger.info(f"Created Firebase user for agent: {agent_email} (UID: {user.uid})")
                                    except Exception as e:
                                        if "EMAIL_EXISTS" in str(e):
                                            logger.warning(f"Firebase user already exists for agent {agent_email}, continuing with agent setup")
                                        else:
                                            logger.error(f"Unexpected Firebase error for agent {agent_email}: {e}")
                                            # Continue anyway - Firebase user existence is not critical for agent setup

                                except Exception as e:
                                    logger.error(f"Error managing Firebase account for agent {agent_email}: {e}")
                                    # Continue with agent setup even if Firebase operations fail

                                # Add to human_agents table
                                await conn.execute(
                                    """
                                    INSERT INTO human_agents (email, status, confirmation_token, auto_generated_password)
                                    VALUES ($1, 'pending', $2, $3)
                                    ON CONFLICT (email)
                                    DO UPDATE SET confirmation_token = $2, status = 'pending', auto_generated_password = $3
                                    """,
                                    agent_email, token, generated_password
                                )

                                # Send confirmation email
                                try:
                                    from shared.email_service import create_email_service
                                    email_service = create_email_service(conn)
                                    await email_service.send_agent_confirmation_email(agent_email, token, "system", generated_password)
                                    logger.info(f"Confirmation email sent to agent: {agent_email}")
                                except Exception as e:
                                    logger.error(f"Error sending confirmation email to agent {agent_email}: {e}")

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
                            "SELECT id, status, confirmation_token FROM human_agents WHERE email = $1",
                            email
                        )
                        
                        if existing:
                            logger.info(f"Agent {email} exists with status: {existing['status']}")
                            if existing['status'] == 'confirmed':
                                # Already confirmed, skip
                                logger.info(f"Agent {email} already confirmed, skipping email")
                                continue
                            elif existing['status'] == 'pending':
                                # Resend confirmation email with existing password
                                token = existing['confirmation_token']
                                # Get existing password
                                existing_with_password = await conn.fetchrow(
                                    "SELECT confirmation_token, auto_generated_password FROM human_agents WHERE email = $1",
                                    email
                                )
                                password = existing_with_password.get('auto_generated_password') if existing_with_password else None
                                # If no password exists, generate one and store it
                                if not password:
                                    from services.configuration_service.human_agents import generate_password
                                    password = generate_password()
                                    await conn.execute(
                                        "UPDATE human_agents SET auto_generated_password = $1 WHERE email = $2",
                                        password, email
                                    )
                                confirmation_link = generate_confirmation_link(token)
                                logger.info(f"Resending confirmation email to pending agent {email}")
                                email_result = await email_service.send_confirmation_email(email, confirmation_link, password)
                                logger.info(f"Email send result for {email}: {email_result}")
                                if email_result:
                                    agents_emailed.append(email)
                                    logger.info(f"✅ Confirmation email resent to {email}")
                                else:
                                    logger.error(f"❌ Failed to resend confirmation email to {email}")
                                continue
                        
                        # Create new agent with auto-generated password
                        logger.info(f"Creating new agent record for {email}")
                        token = generate_confirmation_token()
                        from services.configuration_service.human_agents import generate_password
                        password = generate_password()
                        agent_id = await conn.fetchval(
                            """
                            INSERT INTO human_agents (email, status, confirmation_token, auto_generated_password)
                            VALUES ($1, 'pending', $2, $3)
                            RETURNING id::text
                            """,
                            email, token, password
                        )
                        logger.info(f"New agent created with ID: {agent_id}, sending confirmation email to {email}")
                        
                        # Generate confirmation link and send confirmation email with password
                        confirmation_link = generate_confirmation_link(token)
                        email_result = await email_service.send_confirmation_email(email, confirmation_link, password)
                        logger.info(f"Email send result for {email}: {email_result}")
                        if email_result:
                            agents_emailed.append(email)
                            logger.info(f"✅ Confirmation email sent to {email}")
                        else:
                            logger.error(f"❌ Failed to send confirmation email to {email}")
                    
                    if agents_emailed:
                        logger.info(f"✅ Successfully sent emails to {len(agents_emailed)} agent(s): {', '.join(agents_emailed)}")
                    else:
                        logger.warning(f"⚠️ No emails were sent. Processed {len(config.human_agents)} agent(s) but none received emails.")
                except Exception as e:
                    # Don't fail the entire save if email sending fails
                    logger.error(f"❌ Error sending human agent emails: {e}", exc_info=True)
                    logger.error(f"Error type: {type(e).__name__}")
            
            # Handle deletion of agents that are no longer in the list
            if config.human_agents is not None:
                try:
                    # Get all current agents from the database
                    current_agents = await conn.fetch(
                        "SELECT email FROM human_agents WHERE status IN ('confirmed', 'pending')"
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
            
            return {"success": True, "message": "Configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving configuration: {str(e)}")


# Widget Configuration Endpoints
@app.get("/api/v1/configuration/widget")
async def get_widget_config():
    """Get widget configuration"""
    from fastapi.responses import JSONResponse

    try:
        async with get_db_connection() as conn:
            # Get main widget configuration
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
                    profile_picture_url,
                    chat_icon_url,
                    profile_zoom,
                    chat_icon_zoom,
                    profile_position,
                    chat_icon_position,
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
                "profile_picture_url": row["profile_picture_url"],
                "chat_icon_url": row["chat_icon_url"],
                "profile_zoom": float(row["profile_zoom"]) if row["profile_zoom"] is not None else 1.0,
                "chat_icon_zoom": float(row["chat_icon_zoom"]) if row["chat_icon_zoom"] is not None else 1.0,
                "profile_position": row["profile_position"] if row["profile_position"] is not None and isinstance(row["profile_position"], dict) else {"x": 0, "y": 0},
                "chat_icon_position": row["chat_icon_position"] if row["chat_icon_position"] is not None and isinstance(row["chat_icon_position"], dict) else {"x": 0, "y": 0},
                "profile_picture_filename": row["profile_picture_filename"],
                "chat_icon_filename": row["chat_icon_filename"]
            }
            response = JSONResponse(content=data)
            response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
            return response
    except Exception as e:
        logger.error(f"Error fetching widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching widget configuration: {str(e)}")


@app.post("/api/v1/configuration/widget")
async def save_widget_config(config: WidgetConfigRequest):
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

