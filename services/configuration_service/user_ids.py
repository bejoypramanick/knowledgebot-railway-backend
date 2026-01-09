"""
User Unique IDs Endpoints
Handles generation and retrieval of unique IDs for users, agents, and admins.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
import logging
import sys
from pathlib import Path
from datetime import datetime
import uuid
import random
import string

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["user-ids"])


class UniqueIdRequest(BaseModel):
    email: Optional[str] = None
    role: str = 'customer'  # 'customer', 'agent', or 'admin'


class UniqueIdResponse(BaseModel):
    unique_id: str
    email: Optional[str] = None
    role: str
    created: bool  # True if newly created, False if existing


def generate_unique_id(role: str) -> str:
    """Generate a unique ID with role prefix."""
    prefix = 'ADM' if role == 'admin' else ('AGT' if role == 'agent' else 'CUS')
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}-{timestamp}-{random_part}"


@router.post("/unique-id", response_model=UniqueIdResponse)
async def get_or_create_unique_id(
    request: UniqueIdRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Get or create a unique ID for a user.
    If email is provided, returns existing ID or creates new one.
    If email is None (anonymous user), creates a temporary ID.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            role = request.role.lower()
            if role not in ['customer', 'agent', 'admin']:
                raise HTTPException(status_code=400, detail="Role must be 'customer', 'agent', or 'admin'")
            
            # For anonymous users (no email), generate temporary ID
            if not request.email:
                temp_id = f"TEMP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"
                return UniqueIdResponse(
                    unique_id=temp_id,
                    email=None,
                    role=role,
                    created=True
                )
            
            # Check if unique ID already exists for this email and role
            existing = await conn.fetchrow(
                """
                SELECT unique_id, created_at 
                FROM user_unique_ids 
                WHERE email = $1 AND role = $2
                """,
                request.email, role
            )
            
            if existing:
                logger.info(f"Found existing unique ID for {request.email} ({role})")
                return UniqueIdResponse(
                    unique_id=existing['unique_id'],
                    email=request.email,
                    role=role,
                    created=False
                )
            
            # Generate new unique ID
            unique_id = generate_unique_id(role)
            
            # Ensure uniqueness (retry if collision)
            max_retries = 5
            for attempt in range(max_retries):
                existing_id = await conn.fetchval(
                    "SELECT unique_id FROM user_unique_ids WHERE unique_id = $1",
                    unique_id
                )
                if not existing_id:
                    break
                unique_id = generate_unique_id(role)
            
            # Insert new unique ID
            await conn.execute(
                """
                INSERT INTO user_unique_ids (email, unique_id, role)
                VALUES ($1, $2, $3)
                ON CONFLICT (email, role) DO UPDATE
                SET updated_at = CURRENT_TIMESTAMP
                RETURNING unique_id
                """,
                request.email, unique_id, role
            )
            
            logger.info(f"Created new unique ID {unique_id} for {request.email} ({role})")
            return UniqueIdResponse(
                unique_id=unique_id,
                email=request.email,
                role=role,
                created=True
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting/creating unique ID: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/unique-id", response_model=UniqueIdResponse)
async def get_unique_id(
    email: Optional[str] = Query(None, description="User email"),
    role: str = Query('customer', description="User role"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get existing unique ID for a user.
    Returns 404 if not found.
    """
    try:
        # Use get_db_connection to ensure database is initialized
        from services.configuration_service.main import get_db_connection
        async with get_db_connection() as conn:
            role = role.lower()
            if role not in ['customer', 'agent', 'admin']:
                raise HTTPException(status_code=400, detail="Role must be 'customer', 'agent', or 'admin'")
            
            if not email:
                raise HTTPException(status_code=400, detail="Email is required for GET request")
            
            result = await conn.fetchrow(
                """
                SELECT unique_id, role, created_at
                FROM user_unique_ids 
                WHERE email = $1 AND role = $2
                """,
                email, role
            )
            
            if not result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unique ID not found for email {email} with role {role}"
                )
            
            return UniqueIdResponse(
                unique_id=result['unique_id'],
                email=email,
                role=role,
                created=False
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting unique ID: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
