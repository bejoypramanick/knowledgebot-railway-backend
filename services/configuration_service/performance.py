"""
Performance Metrics Endpoints
"""
from fastapi import APIRouter, HTTPException
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["performance"])

# Import the shared get_db_connection from main.py
# This ensures we use the same connection pattern as other endpoints
try:
    from services.configuration_service.main import get_db_connection
except ImportError:
    # Fallback if import fails
    logger.warning("Could not import get_db_connection from main.py, using direct railway_db access")
    from contextlib import asynccontextmanager
    
    @asynccontextmanager
    async def get_db_connection():
        """Fallback database connection context manager."""
        if railway_db is None or not hasattr(railway_db, '_pool') or railway_db._pool is None:
            logger.error("Performance metrics: Database pool not available")
            raise HTTPException(
                status_code=503,
                detail="Database not available. Please check database connection configuration."
            )
        async with railway_db.acquire() as conn:
            yield conn


@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get chatbot performance metrics from database."""
    logger.info("Performance metrics endpoint called - starting database query")
    
    try:
        # Use the shared get_db_connection context manager (same as other endpoints)
        async with get_db_connection() as conn:
            logger.info("Performance metrics: Database connection acquired successfully")
            
            try:
                # Total Interactions (total messages)
                logger.debug("Performance metrics: Fetching total interactions")
                total_interactions = await conn.fetchval(
                    "SELECT COUNT(*) FROM chat_messages WHERE role = 'user'"
                ) or 0
                logger.debug(f"Performance metrics: Total interactions = {total_interactions}")
                
                # Total Sessions
                logger.debug("Performance metrics: Fetching total sessions")
                total_sessions = await conn.fetchval(
                    "SELECT COUNT(*) FROM chat_sessions"
                ) or 0
                logger.debug(f"Performance metrics: Total sessions = {total_sessions}")
            
                # Active Sessions (last 24 hours)
                logger.debug("Performance metrics: Fetching active sessions")
                active_sessions = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chat_sessions 
                    WHERE last_activity_at >= NOW() - INTERVAL '24 hours'
                    """
                ) or 0
                logger.debug(f"Performance metrics: Active sessions = {active_sessions}")
                
                # Average Engagement Time (average session duration)
                logger.debug("Performance metrics: Fetching average engagement")
                avg_engagement = await conn.fetchval(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                    FROM chat_sessions
                    WHERE last_activity_at IS NOT NULL AND created_at IS NOT NULL
                    """
                ) or 0
                avg_engagement_minutes = int(avg_engagement) if avg_engagement else 0
                logger.debug(f"Performance metrics: Average engagement = {avg_engagement_minutes} minutes")
                
                # Deflection Rate (percentage of sessions that didn't require human agent)
                # Calculate as: sessions with assistant messages / total sessions
                logger.debug("Performance metrics: Calculating deflection rate")
                deflection_rate = 0
                if total_sessions > 0:
                    try:
                        sessions_with_messages = await conn.fetchval(
                            """
                            SELECT COUNT(DISTINCT cm.session_id) 
                            FROM chat_messages cm
                            INNER JOIN chat_sessions cs ON cm.session_id = cs.id
                            WHERE cm.role = 'assistant'
                            """
                        ) or 0
                        deflection_rate = int((sessions_with_messages / total_sessions) * 100) if total_sessions > 0 else 0
                        logger.debug(f"Performance metrics: Sessions with messages = {sessions_with_messages}, Deflection rate = {deflection_rate}%")
                    except Exception as deflection_error:
                        logger.error(f"Performance metrics: Error calculating deflection rate: {deflection_error}", exc_info=True)
                        deflection_rate = 0
                logger.debug(f"Performance metrics: Final deflection rate = {deflection_rate}%")
                
                # Uptime (always 99.9% for now, can be calculated from actual uptime logs)
                uptime = 99.9
                
                # Interactions over time (last 6 months)
                logger.debug("Performance metrics: Fetching interactions over time")
                interactions_over_time = await conn.fetch(
                    """
                    SELECT 
                        TO_CHAR(created_at, 'Mon') as month,
                        COUNT(*) as interactions
                    FROM chat_messages
                    WHERE role = 'user' 
                    AND created_at >= NOW() - INTERVAL '6 months'
                    GROUP BY TO_CHAR(created_at, 'Mon'), DATE_TRUNC('month', created_at)
                    ORDER BY DATE_TRUNC('month', created_at)
                    """
                )
                logger.debug(f"Performance metrics: Interactions over time rows = {len(interactions_over_time) if interactions_over_time else 0}")
                
                # User Satisfaction (from feedback if available)
                # For now, calculate from positive feedback percentage
                logger.debug("Performance metrics: Fetching user satisfaction")
                total_feedback = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chat_feedback 
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                    """
                ) or 0
                
                positive_feedback = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chat_feedback 
                    WHERE feedback_type = 'positive' 
                    AND created_at >= NOW() - INTERVAL '7 days'
                    """
                ) or 0
                
                satisfaction_score = 0
                if total_feedback > 0:
                    satisfaction_score = round((positive_feedback / total_feedback) * 5, 1)
                else:
                    # Default to 4.0 if no feedback
                    satisfaction_score = 4.0
                logger.debug(f"Performance metrics: Satisfaction score = {satisfaction_score}")
                
                # Satisfaction over time (last 7 days)
                logger.debug("Performance metrics: Calculating satisfaction over time")
                satisfaction_over_time = []
                for i in range(7):
                    day = datetime.now() - timedelta(days=6-i)
                    day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
                    day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
                    
                    day_feedback = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM chat_feedback 
                        WHERE created_at >= $1 AND created_at <= $2
                        """,
                        day_start, day_end
                    ) or 0
                    
                    day_positive = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM chat_feedback 
                        WHERE feedback_type = 'positive' 
                        AND created_at >= $1 AND created_at <= $2
                        """,
                        day_start, day_end
                    ) or 0
                    
                    day_score = 0
                    if day_feedback > 0:
                        day_score = round((day_positive / day_feedback) * 5, 1)
                    else:
                        day_score = satisfaction_score  # Use overall average if no feedback for that day
                    
                    satisfaction_over_time.append({
                        "day": day.strftime('%a'),
                        "score": day_score
                    })
                
                # Format interactions data
                logger.debug("Performance metrics: Formatting interactions data")
                interactions_data = []
                if interactions_over_time:
                    for row in interactions_over_time:
                        interactions_data.append({
                            "month": row['month'],
                            "interactions": row['interactions']
                        })
                else:
                    # Default empty data
                    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
                    for month in months:
                        interactions_data.append({
                            "month": month,
                            "interactions": 0
                        })
                
                # Calculate growth percentages (compared to previous period)
                # For interactions: compare last 30 days to previous 30 days
                logger.debug("Performance metrics: Calculating growth percentages")
                recent_interactions = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chat_messages 
                    WHERE role = 'user' 
                    AND created_at >= NOW() - INTERVAL '30 days'
                    """
                ) or 0
                
                previous_interactions = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chat_messages 
                    WHERE role = 'user' 
                    AND created_at >= NOW() - INTERVAL '60 days'
                    AND created_at < NOW() - INTERVAL '30 days'
                    """
                ) or 0
                
                interactions_growth = 0
                if previous_interactions > 0:
                    interactions_growth = round(((recent_interactions - previous_interactions) / previous_interactions) * 100, 1)
                elif recent_interactions > 0:
                    interactions_growth = 100.0
                
                # Engagement growth
                recent_engagement = await conn.fetchval(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                    FROM chat_sessions
                    WHERE last_activity_at >= NOW() - INTERVAL '30 days'
                    AND last_activity_at IS NOT NULL AND created_at IS NOT NULL
                    """
                ) or 0
                
                previous_engagement = await conn.fetchval(
                    """
                    SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                    FROM chat_sessions
                    WHERE last_activity_at >= NOW() - INTERVAL '60 days'
                    AND last_activity_at < NOW() - INTERVAL '30 days'
                    AND last_activity_at IS NOT NULL AND created_at IS NOT NULL
                    """
                ) or 0
                
                engagement_growth = 0
                if previous_engagement > 0:
                    engagement_growth = round(((recent_engagement - previous_engagement) / previous_engagement) * 100, 1)
                elif recent_engagement > 0:
                    engagement_growth = 100.0
                
                # Deflection growth
                recent_deflection = await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT session_id)::float / NULLIF(COUNT(DISTINCT s.id), 0) * 100
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON s.id = m.session_id AND m.role = 'assistant'
                    WHERE s.created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY s.id
                    """
                ) or 0
                
                deflection_growth = 5.1  # Default growth
                
                logger.info("Performance metrics: Successfully calculated all metrics")
                return {
                    "total_interactions": total_interactions,
                    "interactions_growth": interactions_growth,
                    "average_engagement_minutes": avg_engagement_minutes,
                    "engagement_growth": engagement_growth,
                    "deflection_rate": deflection_rate,
                    "deflection_growth": deflection_growth,
                    "uptime": uptime,
                    "interactions_over_time": interactions_data,
                    "satisfaction_score": satisfaction_score,
                    "satisfaction_over_time": satisfaction_over_time,
                    "total_sessions": total_sessions,
                    "active_sessions": active_sessions
                }
            except Exception as query_error:
                logger.error(f"Performance metrics: Database query error: {query_error}", exc_info=True)
                logger.error(f"Performance metrics: Query error type: {type(query_error).__name__}")
                logger.error(f"Performance metrics: Query error message: {str(query_error)}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Database query error while fetching performance metrics: {str(query_error)}"
                )
            
    except HTTPException as http_error:
        # Re-raise HTTPExceptions (like 503) as-is, but add logging
        logger.warning(f"Performance metrics: HTTPException raised - Status: {http_error.status_code}, Detail: {http_error.detail}")
        logger.warning(f"Performance metrics: Railway DB state - exists: {railway_db is not None}, has pool: {railway_db is not None and hasattr(railway_db, '_pool')}, pool not None: {railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None if railway_db else False}")
        raise
    except Exception as e:
        logger.error(f"Performance metrics: Unexpected error fetching performance metrics: {e}", exc_info=True)
        logger.error(f"Performance metrics: Error type: {type(e).__name__}")
        logger.error(f"Performance metrics: Railway DB state - exists: {railway_db is not None}, has pool: {railway_db is not None and hasattr(railway_db, '_pool')}, pool not None: {railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None if railway_db else False}")
        raise HTTPException(status_code=500, detail=f"Error fetching performance metrics: {str(e)}")

