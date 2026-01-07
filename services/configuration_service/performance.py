"""
Performance Metrics Endpoints
"""
from fastapi import APIRouter, HTTPException
import os
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db, init_railway_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["performance"])


async def get_db_connection():
    """Get database connection, initializing if needed."""
    if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
        return railway_db
    
    # Initialize database if not already initialized
    database_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        await init_railway_db(database_url)
        return railway_db
    
    return None


@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get chatbot performance metrics from database."""
    try:
        db = await get_db_connection()
        if not db or not hasattr(db, '_pool') or db._pool is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        async with db.acquire() as conn:
            # Total Interactions (total messages)
            total_interactions = await conn.fetchval(
                "SELECT COUNT(*) FROM chat_messages WHERE role = 'user'"
            ) or 0
            
            # Total Sessions
            total_sessions = await conn.fetchval(
                "SELECT COUNT(*) FROM chat_sessions"
            ) or 0
            
            # Active Sessions (last 24 hours)
            active_sessions = await conn.fetchval(
                """
                SELECT COUNT(*) FROM chat_sessions 
                WHERE last_activity_at >= NOW() - INTERVAL '24 hours'
                """
            ) or 0
            
            # Average Engagement Time (average session duration)
            avg_engagement = await conn.fetchval(
                """
                SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                FROM chat_sessions
                WHERE last_activity_at IS NOT NULL AND created_at IS NOT NULL
                """
            ) or 0
            avg_engagement_minutes = int(avg_engagement) if avg_engagement else 0
            
            # Deflection Rate (percentage of sessions that didn't require human agent)
            # For now, we'll calculate as: sessions with > 0 messages / total sessions
            deflection_rate = 0
            if total_sessions > 0:
                sessions_with_messages = await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT session_id) 
                    FROM chat_messages 
                    WHERE role = 'assistant'
                    """
                ) or 0
                deflection_rate = int((sessions_with_messages / total_sessions) * 100) if total_sessions > 0 else 0
            
            # Uptime (always 99.9% for now, can be calculated from actual uptime logs)
            uptime = 99.9
            
            # Interactions over time (last 6 months)
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
            
            # User Satisfaction (from feedback if available)
            # For now, calculate from positive feedback percentage
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
            
            # Satisfaction over time (last 7 days)
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
            
    except Exception as e:
        logger.error(f"Error fetching performance metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching performance metrics: {str(e)}")

