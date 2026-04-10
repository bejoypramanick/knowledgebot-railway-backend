
import asyncio
import os
from shared.sqlalchemy_db import init_database, get_db_connection

async def check_file():
    db_url = os.getenv("DATABASE_URL")
    await init_database(db_url)
    
    file_id = "019d6eff-2004-778e-9cea-090e2d0cf3a1"
    
    async with get_db_connection() as conn:
        row = await conn.fetchrow("SELECT id, processing_status, updated_at FROM file_uploads WHERE id = $1", file_id)
        print(f"File Record: {row}")
        
        # Also check for any constraints
        constraints = await conn.fetch("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'file_uploads'::regclass")
        for c in constraints:
            print(f"Constraint: {c}")

if __name__ == "__main__":
    asyncio.run(check_file())
