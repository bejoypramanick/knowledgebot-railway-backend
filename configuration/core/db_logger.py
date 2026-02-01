"""
Database Query Logging Utility
Provides consistent logging for all database operations across microservices
"""
from typing import Any, List, Optional, Union
import asyncpg
import logging

logger = logging.getLogger(__name__)

def log_query(query: str, params: Optional[List[Any]] = None, result: Optional[Any] = None, operation: str = "EXECUTE"):
    """Log database query with parameters and results"""
    logger.info(f"🔍 DB Query [{operation}]: {query.strip()}")
    if params:
        logger.info(f"🔍 Parameters: {params}")
    if result is not None:
        if isinstance(result, str):
            logger.info(f"✅ DB Result: {result}")
        elif hasattr(result, '__len__'):
            logger.info(f"✅ DB Result: {len(result)} rows affected/returned")
        else:
            logger.info(f"✅ DB Result: {result}")

async def execute_with_logging(conn: asyncpg.Connection, query: str, *params, operation: str = "EXECUTE"):
    """Execute query with consistent logging"""
    logger.info(f"🔍 DEBUG: execute_with_logging called for operation={operation}")
    logger.info(f"🔍 DEBUG: Query={query.strip()}")
    logger.info(f"🔍 DEBUG: Params={list(params) if params else None}")
    
    log_query(query, list(params) if params else None, operation=operation)
    logger.info(f"🔍 DEBUG: About to execute query")
    result = await conn.execute(query, *params)
    logger.info(f"🔍 DEBUG: Query executed, result={result}")
    log_query(query, list(params) if params else None, result, operation)
    logger.info(f"🔍 DEBUG: execute_with_logging completed")
    return result

async def fetch_with_logging(conn: asyncpg.Connection, query: str, *params, operation: str = "FETCH"):
    """Fetch query with consistent logging"""
    log_query(query, list(params) if params else None, operation=operation)
    result = await conn.fetch(query, *params)
    log_query(query, list(params) if params else None, result, operation)
    return result

async def fetchrow_with_logging(conn: asyncpg.Connection, query: str, *params, operation: str = "FETCHROW"):
    """Fetch single row query with consistent logging"""
    log_query(query, list(params) if params else None, operation=operation)
    result = await conn.fetchrow(query, *params)
    log_query(query, list(params) if params else None, result, operation)
    return result

async def fetchval_with_logging(conn: asyncpg.Connection, query: str, *params, operation: str = "FETCHVAL"):
    """Fetch single value query with consistent logging"""
    log_query(query, list(params) if params else None, operation=operation)
    result = await conn.fetchval(query, *params)
    log_query(query, list(params) if params else None, result, operation)
    return result
