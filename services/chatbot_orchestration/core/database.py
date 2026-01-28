import logging
import asyncio
from shared.config import settings
from shared.db import init_railway_db, init_neon_db, railway_db, neon_db

logger = logging.getLogger(__name__)

# Lazy database initialization for serverless optimization
async def get_railway_db():
    """Get Railway database connection, initializing if needed."""
    # We need to access the global railway_db from shared.db
    # Since we imported it, we are referring to the same object reference
    # However, init_railway_db updates the module-level variable in shared.db?
    # Actually, shared.db defines railway_db = None. init_railway_db updates it.
    # So we should be fine just using the imported railway_db, but we need to check if it's None.
    # But wait, 'from shared.db import railway_db' imports the value at that time (None).
    # We should access it from the module if we want the updated value, or trust init_railway_db returns it.
    
    # Better approach: Use the one from shared.db directly if possible, or rely on internal tracking?
    # The original code used 'global railway_db' which implies it was a module-level variable in main.py
    # initialized by 'from shared.db import ..., railway_db'.
    # If main.py says 'global railway_db', it refers to the name in main.py namespace.
    # But 'railway_db' was imported. In Python, 'from X import Y' creates a local name Y pointing to the value.
    # If X.Y changes, local Y does not. BUT if Y is mutable object it's fine. None is immutable.
    # So we must call init_railway_db which returns the db object.
    
    # Let's see how init_railway_db works. It likely uses a singleton pattern or global in shared.db.
    # To be safe, we will rely on init_railway_db to return the connection.

    try:
        # Check if already initialized? 
        # shared.db.railway_db is the source of truth if we import the module
        import shared.db as db_module
        if db_module.railway_db is not None:
             return db_module.railway_db

        if settings.railway_postgres_url:
            logger.info("🔄 Lazy initializing Railway PostgreSQL database...")
            # This updates db_module.railway_db internally usually
            db = await init_railway_db(settings.railway_postgres_url)
            logger.info("✅ Railway PostgreSQL database initialized")
            return db
    except Exception as e:
        logger.error(f"❌ Failed to initialize Railway PostgreSQL database: {e}")
        raise
    return None

async def get_neon_db():
    """Get Neon database connection, initializing if needed."""
    import shared.db as db_module
    
    try:
        if db_module.neon_db is not None:
            return db_module.neon_db

        if settings.neon_db_url:
            logger.info("🔄 Lazy initializing Neon database...")
            db = await init_neon_db(settings.neon_db_url)
            logger.info("✅ Neon database initialized")
            return db
    except Exception as e:
        logger.error(f"❌ Failed to initialize Neon database: {e}")
        raise
    return None
