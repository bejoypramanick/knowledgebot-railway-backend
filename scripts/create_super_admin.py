"""
Script to create super admin with username 'admin' and password 'admin'
This admin can login with username/password or Google auth
"""
import asyncio
import sys
import os
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.db import init_railway_db, railway_db
from shared.firebase_auth import init_firebase_auth
from firebase_admin import auth
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPER_ADMIN_EMAIL = "admin@globistaan.com"  # Using email format for Firebase
SUPER_ADMIN_PASSWORD = "admin"
SUPER_ADMIN_USERNAME = "admin"

async def create_super_admin():
    """Create super admin user in Firebase and database"""
    try:
        # Initialize Firebase
        init_firebase_auth()
        logger.info("Firebase initialized")
        
        # Initialize database
        database_url = (
            os.getenv("DATABASE_URL") or 
            os.getenv("RAILWAY_POSTGRES_URL") or 
            os.getenv("POSTGRES_URL")
        )
        if not database_url:
            logger.error("DATABASE_URL not set")
            return
        
        await init_railway_db(database_url)
        logger.info("Database initialized")
        
        # Check if super admin already exists in Firebase
        try:
            existing_user = auth.get_user_by_email(SUPER_ADMIN_EMAIL)
            logger.info(f"Super admin already exists in Firebase: {existing_user.uid}")
            # Update password to ensure it's set correctly
            auth.update_user(existing_user.uid, password=SUPER_ADMIN_PASSWORD)
            logger.info("Super admin password updated")
        except auth.UserNotFoundError:
            # Create new super admin user
            user = auth.create_user(
                email=SUPER_ADMIN_EMAIL,
                password=SUPER_ADMIN_PASSWORD,
                display_name="Super Admin",
                email_verified=True,  # Auto-verify super admin
                disabled=False
            )
            logger.info(f"Super admin created in Firebase: {user.uid}")
        
        # Add to database admins table
        async with railway_db.acquire() as conn:
            # Check if admin already exists
            existing_admin = await conn.fetchrow(
                "SELECT id, status FROM admins WHERE email = $1",
                SUPER_ADMIN_EMAIL
            )
            
            if existing_admin:
                # Update to confirmed status
                await conn.execute(
                    """
                    UPDATE admins 
                    SET status = 'confirmed', confirmed_at = NOW()
                    WHERE email = $1
                    """,
                    SUPER_ADMIN_EMAIL
                )
                logger.info("Super admin updated in database")
            else:
                # Insert new admin
                await conn.execute(
                    """
                    INSERT INTO admins (email, status, confirmed_at)
                    VALUES ($1, 'confirmed', NOW())
                    """,
                    SUPER_ADMIN_EMAIL
                )
                logger.info("Super admin added to database")
            
            # Update chatbot_configuration to include super admin
            await conn.execute(
                """
                INSERT INTO chatbot_configuration (admin_user, admin_emails)
                VALUES ($1, ARRAY[$2]::TEXT[])
                ON CONFLICT (admin_user) 
                DO UPDATE SET 
                    admin_emails = CASE 
                        WHEN $2 = ANY(COALESCE(chatbot_configuration.admin_emails, ARRAY[]::TEXT[])) 
                        THEN chatbot_configuration.admin_emails
                        ELSE array_append(COALESCE(chatbot_configuration.admin_emails, ARRAY[]::TEXT[]), $2)
                    END
                """,
                SUPER_ADMIN_EMAIL, SUPER_ADMIN_EMAIL
            )
            logger.info("Super admin added to chatbot configuration")
        
        logger.info("✅ Super admin created successfully!")
        logger.info(f"   Email: {SUPER_ADMIN_EMAIL}")
        logger.info(f"   Password: {SUPER_ADMIN_PASSWORD}")
        logger.info(f"   Username: {SUPER_ADMIN_USERNAME}")
        
    except Exception as e:
        logger.error(f"Error creating super admin: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(create_super_admin())

