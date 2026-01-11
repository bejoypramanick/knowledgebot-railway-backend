"""
Configuration Service - Handles chatbot and widget configuration management
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Union
import os
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import asyncio

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import init_railway_db, close_databases, railway_db

load_dotenv()

# Lock for database initialization to prevent race conditions
_db_init_lock = asyncio.Lock()

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

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        # Initialize database
        database_url = (
            os.getenv("DATABASE_URL") or 
            os.getenv("RAILWAY_POSTGRES_URL") or 
            os.getenv("POSTGRES_URL")
        )
        if database_url:
            try:
                await init_railway_db(database_url)
                logger.info("✅ Database initialized for configuration service")
            except Exception as e:
                logger.error(f"❌ Could not initialize database: {e}")
                logger.error("Configuration endpoints will not work without database connection")
        else:
            logger.error("❌ DATABASE_URL, RAILWAY_POSTGRES_URL, or POSTGRES_URL not set - configuration endpoints will not work")
        
        # Initialize Firebase Auth and Firestore
        try:
            from shared.firebase_auth import init_firebase_auth
            init_firebase_auth()
            logger.info("✅ Firebase Auth and Firestore initialized")
        except Exception as e:
            logger.warning(f"⚠️ Firebase Auth/Firestore not initialized: {e}")
            logger.warning("Authentication endpoints will not work without Firebase")
        
        logger.info(f"🚀 Configuration service started successfully on port {PORT}")
        yield
        
        # Shutdown
        await close_databases()
        logger.info("✅ Configuration service shutdown complete")
    except Exception as e:
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


@asynccontextmanager
async def get_db_connection():
    """Get database connection from shared pool - optimized for performance"""
    # Quick check - if railway_db exists and has a pool, use it directly
    if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
        async with railway_db.acquire() as conn:
            yield conn
        return
    
    # Fallback: Try to initialize if not already initialized (should rarely happen)
    # Use lock to prevent concurrent initialization
    async with _db_init_lock:
        # Check again after acquiring lock - another request might have initialized it
        if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
            async with railway_db.acquire() as conn:
                yield conn
            return
        
        from shared.db import init_railway_db
        
        database_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
        if not database_url:
            raise HTTPException(
                status_code=503, 
                detail="Database not initialized. DATABASE_URL, RAILWAY_POSTGRES_URL, or POSTGRES_URL environment variable not set."
            )
        
        try:
            # Initialize the database and get the instance
            # init_railway_db will reuse existing instance if available
            initialized_db = await init_railway_db(database_url)
            logger.info("✅ Database initialized on-demand for configuration endpoint")
            
            # Verify the pool was created successfully
            if initialized_db is None:
                raise HTTPException(
                    status_code=503,
                    detail="Database initialization returned None"
                )
            
            if not hasattr(initialized_db, '_pool') or initialized_db._pool is None:
                raise HTTPException(
                    status_code=503,
                    detail="Database connection pool not available after initialization"
                )
            
            # Use the initialized database instance directly
            async with initialized_db.acquire() as conn:
                yield conn
        except HTTPException:
            raise
        except Exception as e:
            error_msg = str(e)
            # If we get "too many clients already", don't log the full traceback as it's expected
            if "too many clients already" in error_msg.lower():
                logger.error(f"❌ Database connection limit exceeded. Please wait and retry.")
            else:
                logger.error(f"❌ Failed to initialize database: {e}", exc_info=True)
            raise HTTPException(
                status_code=503, 
                detail=f"Database not initialized. Error: {error_msg}"
            )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "configuration_service",
        "database": "connected" if (railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None) else "disconnected"
    }


# Chatbot Configuration Endpoints
@app.get("/api/v1/configuration/chatbot")
async def get_chatbot_config():
    """Get chatbot configuration"""
    from fastapi.responses import JSONResponse
    
    try:
        async with get_db_connection() as conn:
            # Try to select with hil_enabled, but handle gracefully if column doesn't exist
            # Column must be added manually via migration script
            try:
                row = await conn.fetchrow(
                    """
                    SELECT 
                        admin_user,
                        admin_emails,
                        human_agents,
                        hil_enabled,
                        user_interactions_enabled,
                        error_alerts_enabled,
                        feedback_requests_enabled,
                        response_timeout,
                        remove_pii,
                        restrict_config,
                        response_policy,
                        backup_logs,
                        system_prompt,
                        selected_persona,
                        llm_token_limit_gemini,
                        llm_token_used_gemini,
                        llm_token_limit_deepseek,
                        llm_token_used_deepseek,
                        updated_at
                    FROM chatbot_configuration
                    WHERE admin_user = 'GLOBISTAAN'
                    """
                )
            except Exception as e:
                # If hil_enabled column doesn't exist, select without it and default to True
                if 'hil_enabled' in str(e) or 'column' in str(e).lower():
                    logger.warning("hil_enabled column not found. Please run migration script to add it. Defaulting to True.")
                    row = await conn.fetchrow(
                        """
                        SELECT 
                            admin_user,
                            admin_emails,
                            human_agents,
                            user_interactions_enabled,
                            error_alerts_enabled,
                            feedback_requests_enabled,
                            response_timeout,
                            remove_pii,
                            restrict_config,
                            response_policy,
                            backup_logs,
                            system_prompt,
                            selected_persona,
                            llm_token_limit_gemini,
                            llm_token_used_gemini,
                            llm_token_limit_deepseek,
                            llm_token_used_deepseek,
                            updated_at
                        FROM chatbot_configuration
                        WHERE admin_user = 'GLOBISTAAN'
                        """
                    )
                    # Add hil_enabled with default value
                    if row:
                        row = dict(row)
                        row['hil_enabled'] = True
                else:
                    raise
            
            # Fetch human agents from the human_agents table (not from chatbot_configuration.human_agents)
            # Get all confirmed and pending agents
            human_agents_rows = await conn.fetch(
                """
                SELECT email FROM human_agents 
                WHERE status IN ('confirmed', 'pending')
                ORDER BY email
                """
            )
            human_agents_list = [agent["email"] for agent in human_agents_rows] if human_agents_rows else []
            logger.info(f"Fetched {len(human_agents_list)} human agent(s) from human_agents table: {human_agents_list}")
            
            # Fetch admins from the admins table (source of truth for admin list)
            admin_rows = await conn.fetch(
                """
                SELECT email FROM admins 
                WHERE status IN ('confirmed', 'pending')
                ORDER BY email
                """
            )
            admin_emails_list = [admin["email"] for admin in admin_rows] if admin_rows else []
            logger.info(f"Fetched {len(admin_emails_list)} admin(s) from admins table: {admin_emails_list}")
            
            if not row:
                # Return default configuration with cache headers
                data = {
                    "admin_user": "GLOBISTAAN",
                    "admin_emails": admin_emails_list,
                    "admin_password": "**********",
                    "human_agents": human_agents_list,
                    "hil_enabled": True,  # Default to enabled
                    "notifications": {
                        "user_interactions_enabled": False,
                        "error_alerts_enabled": False,
                        "feedback_requests_enabled": True
                    },
                    "security": {
                        "response_timeout": 30,
                        "remove_pii": False,
                        "restrict_config": False
                    },
                    "response_policy": 30,
                    "data_management": {
                        "backup_logs": False
                    },
                    "persona": {
                        "system_prompt": "",
                        "selected_persona": "friendly-receptionist"
                    },
                    "llm_tokens": {
                        "gemini": {
                            "used": 0,
                            "available": 20000,
                            "limit": 20000
                        },
                        "deepseek": {
                            "used": 0,
                            "available": 150000,
                            "limit": 150000
                        }
                    }
                }
                response = JSONResponse(content=data)
                # Add cache headers for faster loading (5 seconds cache, but allow revalidation)
                response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
                return response
            
            data = {
                "admin_user": row["admin_user"],
                "admin_emails": admin_emails_list,
                "admin_password": "**********",
                "human_agents": human_agents_list,
                "hil_enabled": row.get("hil_enabled", True),  # Default to True if column doesn't exist
                "notifications": {
                    "user_interactions_enabled": row["user_interactions_enabled"],
                    "error_alerts_enabled": row["error_alerts_enabled"],
                    "feedback_requests_enabled": row["feedback_requests_enabled"]
                },
                "security": {
                    "response_timeout": row["response_timeout"],
                    "remove_pii": row["remove_pii"],
                    "restrict_config": row["restrict_config"]
                },
                "response_policy": row["response_policy"],
                "data_management": {
                    "backup_logs": row["backup_logs"]
                },
                "persona": {
                    "system_prompt": row["system_prompt"] or "",
                    "selected_persona": row["selected_persona"]
                },
                "llm_tokens": {
                    "gemini": {
                        "used": row["llm_token_used_gemini"],
                        "available": row["llm_token_limit_gemini"] - row["llm_token_used_gemini"],
                        "limit": row["llm_token_limit_gemini"]
                    },
                    "openai": {
                        "used": row.get("llm_token_used_deepseek", 0),  # Migrate deepseek to openai
                        "available": row.get("llm_token_limit_deepseek", 150000) - row.get("llm_token_used_deepseek", 0),
                        "limit": row.get("llm_token_limit_deepseek", 150000)
                    }
                }
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
            # Build update query dynamically based on provided fields
            updates = []
            values = []
            param_index = 1
            
            if config.admin_emails is not None:
                # Process admin emails - extract emails (passwords will be auto-generated)
                admin_email_list = []
                admin_emails_to_create = []
                
                for admin_item in config.admin_emails:
                    # Handle both dict (AdminAccount) and str formats
                    if isinstance(admin_item, dict):
                        # New format: {email, password} - extract just email
                        email = admin_item.get('email', '')
                        if email:
                            admin_email_list.append(email)
                            admin_emails_to_create.append(email)
                    elif hasattr(admin_item, 'email'):
                        # Pydantic model format - extract just email
                        email = admin_item.email
                        if email:
                            admin_email_list.append(email)
                            admin_emails_to_create.append(email)
                    elif isinstance(admin_item, str):
                        # Old format: just email string
                        admin_email_list.append(admin_item)
                        admin_emails_to_create.append(admin_item)
                
                updates.append(f"admin_emails = ${param_index}::text[]")
                values.append(admin_email_list)
                param_index += 1
                
                # Also update admin_user for backward compatibility (use first admin email if available)
                if len(admin_email_list) > 0:
                    # Check if admin_user is already in updates to avoid duplicate
                    if "admin_user" not in " ".join(updates):
                        updates.append(f"admin_user = ${param_index}")
                        values.append(admin_email_list[0])
                        param_index += 1
                
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
                                try:
                                    # Try to insert with auto_generated_password column
                                    # Column must exist in database (added via migration script)
                                    await conn.execute(
                                        """
                                        INSERT INTO admins (email, status, confirmation_token, auto_generated_password)
                                        VALUES ($1, 'pending', $2, $3)
                                        ON CONFLICT (email) 
                                        DO UPDATE SET confirmation_token = $2, status = 'pending', auto_generated_password = $3
                                        """,
                                        email, token, generated_password
                                    )
                                except Exception as db_error:
                                    # If column doesn't exist, fallback to insert without password column
                                    # Column must be added manually via migration script
                                    if 'auto_generated_password' in str(db_error).lower() or 'column' in str(db_error).lower():
                                        logger.warning(f"auto_generated_password column not found. Please run migration script to add it. Inserting without password column.")
                                        await conn.execute(
                                            """
                                            INSERT INTO admins (email, status, confirmation_token)
                                            VALUES ($1, 'pending', $2)
                                            ON CONFLICT (email) 
                                            DO UPDATE SET confirmation_token = $2, status = 'pending'
                                            """,
                                            email, token
                                        )
                                    else:
                                        raise
                                
                                # Send verification email with generated password
                                await email_service.send_admin_confirmation_email(email, token, "system", generated_password)
                                logger.info(f"Verification email with password sent to admin: {email}")
                                
                            except Exception as e:
                                logger.error(f"Error creating Firebase account for {email}: {e}", exc_info=True)
                                # Continue with other admins even if one fails
                    except Exception as e:
                        logger.error(f"Error processing admin accounts: {e}", exc_info=True)
                        # Don't fail the whole request if admin creation fails
            
            if config.human_agents is not None:
                updates.append(f"human_agents = ${param_index}::text[]")
                values.append(config.human_agents)
                param_index += 1
            
            if config.hil_enabled is not None:
                updates.append(f"hil_enabled = ${param_index}")
                values.append(config.hil_enabled)
                param_index += 1
            
            if config.notifications:
                if config.notifications.user_interactions_enabled is not None:
                    updates.append(f"user_interactions_enabled = ${param_index}")
                    values.append(config.notifications.user_interactions_enabled)
                    param_index += 1
                if config.notifications.error_alerts_enabled is not None:
                    updates.append(f"error_alerts_enabled = ${param_index}")
                    values.append(config.notifications.error_alerts_enabled)
                    param_index += 1
                if config.notifications.feedback_requests_enabled is not None:
                    updates.append(f"feedback_requests_enabled = ${param_index}")
                    values.append(config.notifications.feedback_requests_enabled)
                    param_index += 1
            
            if config.security:
                if config.security.response_timeout is not None:
                    updates.append(f"response_timeout = ${param_index}")
                    values.append(config.security.response_timeout)
                    param_index += 1
                if config.security.remove_pii is not None:
                    updates.append(f"remove_pii = ${param_index}")
                    values.append(config.security.remove_pii)
                    param_index += 1
                if config.security.restrict_config is not None:
                    updates.append(f"restrict_config = ${param_index}")
                    values.append(config.security.restrict_config)
                    param_index += 1
            
            if config.response_policy is not None:
                updates.append(f"response_policy = ${param_index}")
                values.append(config.response_policy)
                param_index += 1
            
            if config.data_management:
                if config.data_management.backup_logs is not None:
                    updates.append(f"backup_logs = ${param_index}")
                    values.append(config.data_management.backup_logs)
                    param_index += 1
            
            if config.persona:
                if config.persona.system_prompt is not None:
                    updates.append(f"system_prompt = ${param_index}")
                    values.append(config.persona.system_prompt)
                    param_index += 1
                if config.persona.selected_persona is not None:
                    updates.append(f"selected_persona = ${param_index}")
                    values.append(config.persona.selected_persona)
                    param_index += 1
            
            if config.llm_tokens:
                if "gemini" in config.llm_tokens:
                    if "used" in config.llm_tokens["gemini"]:
                        updates.append(f"llm_token_used_gemini = ${param_index}")
                        values.append(config.llm_tokens["gemini"]["used"])
                        param_index += 1
                    if "limit" in config.llm_tokens["gemini"]:
                        updates.append(f"llm_token_limit_gemini = ${param_index}")
                        values.append(config.llm_tokens["gemini"]["limit"])
                        param_index += 1
                if "deepseek" in config.llm_tokens:
                    if "used" in config.llm_tokens["deepseek"]:
                        updates.append(f"llm_token_used_deepseek = ${param_index}")
                        values.append(config.llm_tokens["deepseek"]["used"])
                        param_index += 1
                    if "limit" in config.llm_tokens["deepseek"]:
                        updates.append(f"llm_token_limit_deepseek = ${param_index}")
                        values.append(config.llm_tokens["deepseek"]["limit"])
                        param_index += 1
            
            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")
            
            # Use INSERT ... ON CONFLICT to handle upsert
            # Determine admin_user value for INSERT
            admin_user_value = 'GLOBISTAAN'
            if config.admin_emails is not None and len(config.admin_emails) > 0:
                # Extract first email if it's a string, or get email from dict/object
                first_admin = config.admin_emails[0]
                if isinstance(first_admin, str):
                    admin_user_value = first_admin
                elif isinstance(first_admin, dict):
                    admin_user_value = first_admin.get('email', 'GLOBISTAAN')
                elif hasattr(first_admin, 'email'):
                    admin_user_value = first_admin.email
                else:
                    admin_user_value = 'GLOBISTAAN'
            
            # Extract field names from updates
            update_field_names = [u.split(' = ')[0] for u in updates]
            
            # Build INSERT values and placeholders
            insert_field_names = []
            insert_values = []
            insert_placeholders = []
            param_num = 1
            
            # Add admin_user first if not in updates
            if 'admin_user' not in update_field_names:
                insert_field_names.append('admin_user')
                insert_values.append(admin_user_value)
                insert_placeholders.append(f'${param_num}')
                param_num += 1
            
            # Add all update fields to INSERT
            for i, update_clause in enumerate(updates):
                field_name = update_clause.split(' = ')[0]
                insert_field_names.append(field_name)
                insert_values.append(values[i])
                if field_name in ['admin_emails', 'human_agents']:
                    insert_placeholders.append(f'${param_num}::text[]')
                else:
                    insert_placeholders.append(f'${param_num}')
                param_num += 1
            
            # Rebuild UPDATE clause to reference the same parameters as INSERT
            # If admin_user was added to INSERT, UPDATE parameters start from $2
            update_clauses = []
            update_param_start = 2 if 'admin_user' not in update_field_names else 1
            
            for i, update_clause in enumerate(updates):
                field_name = update_clause.split(' = ')[0]
                param_num = update_param_start + i
                if field_name in ['admin_emails', 'human_agents']:
                    update_clauses.append(f"{field_name} = ${param_num}::text[]")
                else:
                    update_clauses.append(f"{field_name} = ${param_num}")
            
            query = f"""
                INSERT INTO chatbot_configuration ({', '.join(insert_field_names)})
                VALUES ({', '.join(insert_placeholders)})
                ON CONFLICT (admin_user) 
                DO UPDATE SET {', '.join(update_clauses)}, updated_at = CURRENT_TIMESTAMP
            """
            
            await conn.execute(query, *insert_values)
            
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
            row = await conn.fetchrow(
                """
                SELECT 
                    display_name,
                    initial_message,
                    auto_show_duration,
                    suggested_messages,
                    keep_showing_suggested,
                    theme,
                    primary_color,
                    use_primary_for_header,
                    chat_bubble_color,
                    align_bubble,
                    profile_picture_url,
                    chat_icon_url,
                    updated_at
                FROM widget_configuration
                WHERE id = 1
                """
            )
            
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
                    "chat_icon_url": None
                }
                response = JSONResponse(content=data)
                response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
                return response
            
            data = {
                "display_name": row["display_name"],
                "initial_message": row["initial_message"],
                "auto_show_duration": row["auto_show_duration"],
                "suggested_messages": row["suggested_messages"] or [],
                "keep_showing_suggested": row["keep_showing_suggested"],
                "theme": row["theme"],
                "primary_color": row["primary_color"],
                "use_primary_for_header": row["use_primary_for_header"],
                "chat_bubble_color": row["chat_bubble_color"],
                "align_bubble": row["align_bubble"],
                "profile_picture_url": row["profile_picture_url"],
                "chat_icon_url": row["chat_icon_url"]
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
            # Build update query dynamically
            updates = []
            values = []
            param_index = 1
            
            fields_map = {
                "display_name": "display_name",
                "initial_message": "initial_message",
                "auto_show_duration": "auto_show_duration",
                "suggested_messages": "suggested_messages",
                "keep_showing_suggested": "keep_showing_suggested",
                "theme": "theme",
                "primary_color": "primary_color",
                "use_primary_for_header": "use_primary_for_header",
                "chat_bubble_color": "chat_bubble_color",
                "align_bubble": "align_bubble",
                "profile_picture_url": "profile_picture_url",
                "chat_icon_url": "chat_icon_url"
            }
            
            for field, db_field in fields_map.items():
                value = getattr(config, field, None)
                if value is not None:
                    updates.append(f"{db_field} = ${param_index}")
                    values.append(value)
                    param_index += 1
            
            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")
            
            # Use INSERT ... ON CONFLICT to handle upsert (assuming single row with id=1)
            # First, check if a row exists
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
    from services.configuration_service.auth import router as auth_router
    from services.configuration_service.chat_log import router as chat_log_router, public_chat_router

    app.include_router(human_agents_router)
    app.include_router(feedback_router)
    app.include_router(token_usage_router)
    app.include_router(admin_management_router)
    app.include_router(auth_router)
    app.include_router(performance_router)
    app.include_router(chat_log_router)
    app.include_router(public_chat_router)  # Public chat endpoints (no auth required)
    logger.info("✅ New endpoints (human agents, feedback, token usage, admin management, auth, chat log) loaded successfully")
except ImportError as e:
    logger.warning(f"⚠️ Could not import new endpoint modules: {e}")
    logger.warning("New endpoints (human agents, feedback, token usage, auth, chat log) will not be available")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)

