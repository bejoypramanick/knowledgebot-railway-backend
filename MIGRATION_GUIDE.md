# Database Migration Guide: SQLAlchemy Only

This guide shows how to migrate all microservices from custom asyncpg code to unified SQLAlchemy.

## **Railway Environment Configuration**

SQLAlchemy reads all settings from Railway environment variables:

```bash
# Required
DATABASE_URL=postgresql+asyncpg://user:pass@host/database

# Optional (uses sensible defaults if not set)
DB_POOL_SIZE=5                    # Min connections
DB_POOL_MAX_OVERFLOW=3            # Additional connections under load
DB_POOL_RECYCLE=3600              # Recycle connections after 1 hour
DB_STATEMENT_TIMEOUT=60000        # Cancel queries after 60 seconds
DB_CONNECT_TIMEOUT=10             # Connection acquisition timeout
DB_COMMAND_TIMEOUT=20             # Command timeout
```

Railway automatically provides `DATABASE_URL`. No additional configuration needed for most deployments.

---

## **Step 1: Update Service Requirements**

For each microservice, add to `requirements.txt`:

```
sqlalchemy>=2.0.23
```

Example for configuration service:
```bash
# configuration/requirements.txt
sqlalchemy>=2.0.23
```

---

## **Step 2: Update Service Startup (main.py)**

### **Before** (Old asyncpg way):
```python
from configuration.core.database_initializer import database_initializer

@app.lifespan
async def lifespan(app):
    try:
        # Old custom initializer
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            app.state.database_url = database_url
            await database_initializer.initialize_and_validate(database_url)
        yield
        await close_databases()
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
```

### **After** (SQLAlchemy):
```python
from shared.sqlalchemy_db import init_database, validate_database, close_database

@app.lifespan
async def lifespan(app):
    try:
        # SQLAlchemy initialization
        await init_database()
        await validate_database()
        yield
        await close_database()
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
```

---

## **Step 3: Update All DAOs**

### **Example: auth_dao.py**

**Before** (asyncpg):
```python
from shared.db import get_db_connection

async def get_user_roles(self, email: str) -> List[Dict[str, Any]]:
    query = """
        SELECT urm.user_role_id, r.role_name, r.role_description, urm.created_at
        FROM user_role_mapping urm
        JOIN users u ON urm.user_id = u.id
        JOIN roles r ON urm.role_id = r.id
        WHERE u.email = $1
        AND u.is_active = true
        AND urm.is_active = true
        ORDER BY r.role_name
    """
    try:
        logger.log_db_operation(query, {"email": email})
        async with get_db_connection() as conn:
            results = await conn.fetch(query, email)
            logger.log_db_query(query, {"email": email}, results)
            return [dict(row) for row in results]
    except Exception as e:
        logger.log_db_query(query, {"email": email}, error=e)
        raise
```

**After** (SQLAlchemy):
```python
from sqlalchemy import select, and_, text
from shared.sqlalchemy_db import get_db_session

async def get_user_roles(self, email: str) -> List[Dict[str, Any]]:
    try:
        async with get_db_session() as session:
            # Option 1: Raw SQL (closest to original)
            query = text("""
                SELECT urm.user_role_id, r.role_name, r.role_description, urm.created_at
                FROM user_role_mapping urm
                JOIN users u ON urm.user_id = u.id
                JOIN roles r ON urm.role_id = r.id
                WHERE u.email = :email
                AND u.is_active = true
                AND urm.is_active = true
                ORDER BY r.role_name
            """)
            result = await session.execute(query, {"email": email})
            rows = result.fetchall()
            return [dict(row._mapping) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching user roles: {e}")
        raise
```

---

## **Step 4: Remove Old Database Code**

Delete these files from each service:

```bash
# Configuration service
rm configuration/core/database_initializer.py
rm configuration/core/db_logger.py

# Chatbot orchestration
rm chatbot_orchestration/core/database_initializer.py
rm chatbot_orchestration/core/db_logger.py

# Health monitoring
rm health_monitoring/core/database_initializer.py

# Knowledgebase ingestion
rm knowledgebase_ingestion/core/database_initializer.py

# (Repeat for any other services)
```

Delete the old shared database file:
```bash
# DEPRECATED - Use shared/sqlalchemy_db.py instead
rm shared/db.py

# DEPRECATED - Use shared/sqlalchemy_db.py instead
rm shared/database.py
```

---

## **Step 5: Update All Imports**

### **Search and replace in all DAOs:**

**From:**
```python
from shared.db import get_db_connection
from shared.database import init_db, get_db_connection
```

**To:**
```python
from shared.sqlalchemy_db import get_db_session
from shared.sqlalchemy_db import init_database, validate_database, close_database
```

---

## **Step 6: Health Check Endpoints**

### **Before:**
```python
@app.get("/health")
async def health_check():
    db_status = "not_checked"
    if railway_db is not None and hasattr(railway_db, '_pool'):
        db_status = "connected"
    return {"status": "healthy", "database": db_status}
```

### **After:**
```python
from shared.sqlalchemy_db import health_check

@app.get("/health")
async def health_endpoint():
    db_health = await health_check()
    status_code = 200 if db_health["status"] == "healthy" else 503
    return JSONResponse(db_health, status_code=status_code)
```

---

## **Complete Example: Configuration Service**

### **main.py**
```python
from fastapi import FastAPI
from contextlib import asynccontextmanager
from shared.sqlalchemy_db import init_database, validate_database, close_database, health_check
from shared.otel_logger import get_otel_logger
from configuration.routers import router as config_router

logger = get_otel_logger("config_service", "configuration")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting configuration service...")
    try:
        await init_database()
        await validate_database()
        logger.info("✅ Configuration service started")
    except Exception as e:
        logger.error(f"❌ Failed to start: {e}")
        raise

    yield

    # Shutdown
    logger.info("🛑 Shutting down configuration service...")
    try:
        await close_database()
        logger.info("✅ Configuration service stopped")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")

app = FastAPI(title="Configuration Service", lifespan=lifespan)
app.include_router(config_router, prefix="/api/v1/configuration")

@app.get("/health")
async def health():
    return await health_check()
```

### **configuration/dao/auth_dao.py**
```python
from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("auth_dao", "configuration")

class AuthDAO:
    async def get_user_roles(self, email: str) -> list:
        """Get all roles for a user."""
        try:
            async with get_db_session() as session:
                query = text("""
                    SELECT urm.user_role_id, r.role_name, r.role_description
                    FROM user_role_mapping urm
                    JOIN users u ON urm.user_id = u.id
                    JOIN roles r ON urm.role_id = r.id
                    WHERE u.email = :email AND u.is_active = true
                """)
                result = await session.execute(query, {"email": email})
                return [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            logger.error(f"Error fetching user roles for {email}: {e}")
            raise
```

---

## **Checklist for Migration**

- [ ] Add `sqlalchemy>=2.0.23` to all service requirements.txt
- [ ] Update main.py to use `init_database()` instead of custom initializer
- [ ] Update all DAOs to use `get_db_session()` instead of `get_db_connection()`
- [ ] Update health check endpoints to use `health_check()` from SQLAlchemy
- [ ] Delete old `database_initializer.py` files from all services
- [ ] Delete old `shared/db.py` (after verifying no imports remain)
- [ ] Test each service locally
- [ ] Deploy to Railway

---

## **Railway Configuration**

In Railway environment variables, only set:

```
DATABASE_URL=postgresql+asyncpg://...
```

Everything else uses sensible defaults. SQLAlchemy will:
- ✅ Create a pool with 5 min connections
- ✅ Allow up to 3 additional connections under load
- ✅ Recycle connections every 1 hour
- ✅ Health check each connection before use
- ✅ Timeout queries at 60 seconds
- ✅ Timeout connection acquisition at 10 seconds

---

## **Benefits After Migration**

✅ **Single database manager** - All services use same proven code
✅ **Railway configuration** - Uses environment variables
✅ **Battle-tested** - SQLAlchemy is used by millions of applications
✅ **No more custom code** - Rely on proven library
✅ **Easier maintenance** - Update once, fixes all services
✅ **Better monitoring** - Built-in health checks
✅ **Automatic recovery** - Connection recycling and health checks
✅ **Cleaner codebase** - Remove 400+ lines of custom database code

---

## **Support**

If you encounter issues:
1. Check Railway environment has `DATABASE_URL` set
2. Check service logs for SQLAlchemy initialization errors
3. Verify asyncpg is in requirements.txt
4. Ensure all imports updated to use `shared.sqlalchemy_db`
