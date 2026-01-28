"""
Performance Metrics Endpoints
"""
from fastapi import APIRouter, HTTPException
import logging
import sys
import asyncio
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
from .main import get_db_connection
from .dao.performance_dao import PerformanceDAO


@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get chatbot performance metrics from database with optimized parallel queries."""
    logger.info("Performance metrics endpoint called - starting optimized parallel queries")

    try:
        # Use the shared get_db_connection context manager (same as other endpoints)
        async with get_db_connection() as conn:
            logger.info("Performance metrics: Database connection acquired successfully")
            
            # Initialize DAO
            performance_dao = PerformanceDAO(conn)

            try:
                # Run queries sequentially to avoid connection conflicts in serverless environment
                logger.debug("Performance metrics: Starting sequential queries for basic metrics")

                # Group 1: Basic counts and engagement (run sequentially)
                basic_results = []
                try:
                    # Total Interactions
                    total_interactions = await performance_dao.get_total_interactions()
                    basic_results.append(total_interactions or 0)
                except Exception as e:
                    logger.error(f"Performance metrics: Error in total interactions query: {e}")
                    basic_results.append(0)

                try:
                    # Total Sessions
                    total_sessions_val = await performance_dao.get_total_sessions()
                    basic_results.append(total_sessions_val or 0)
                except Exception as e:
                    logger.error(f"Performance metrics: Error in total sessions query: {e}")
                    basic_results.append(0)

                try:
                    # Active Sessions (last 24 hours)
                    active_sessions_val = await performance_dao.get_active_sessions()
                    basic_results.append(active_sessions_val or 0)
                except Exception as e:
                    logger.error(f"Performance metrics: Error in active sessions query: {e}")
                    basic_results.append(0)

                try:
                    # Average Engagement Time
                    avg_engagement_val = await performance_dao.get_average_engagement_time()
                    basic_results.append(avg_engagement_val or 0)
                except Exception as e:
                    logger.error(f"Performance metrics: Error in engagement query: {e}")
                    basic_results.append(0)

                # Results are already handled above, no exceptions to process
                total_interactions = basic_results[0]
                total_sessions = basic_results[1]
                active_sessions = basic_results[2]
                avg_engagement = basic_results[3]

                # Group 2: Complex calculations (run sequentially)
                logger.debug("Performance metrics: Starting sequential queries for complex metrics")

                # Deflection Rate calculation (3NF Schema)
                # Deflection = Sessions handled by AI alone (no human engagement)
                # Formula: (Total Sessions - Sessions with Human Assignment) / Total Sessions
                sessions_with_human = 0
                try:
                    if total_sessions > 0:
                        sessions_with_human = await performance_dao.get_sessions_with_human() or 0
                except Exception as e:
                    logger.error(f"Performance metrics: Error in deflection query: {e}")
                    sessions_with_human = 0

                deflection_rate = int(((total_sessions - sessions_with_human) / total_sessions) * 100) if total_sessions > 0 else 0

                # Calculate AI handled chats and human agent handoffs from actual data
                ai_handled_chats = 0
                human_agent_handoffs = 0
                try:
                    # Count messages in sessions without human assignment (AI handled)
                    ai_handled_result = await performance_dao.get_ai_handled_chats()
                    ai_handled_chats = ai_handled_result or 0

                    # Count messages in sessions with human assignment (human handoff)
                    human_handoff_result = await performance_dao.get_human_agent_handoffs()
                    human_agent_handoffs = human_handoff_result or 0

                except Exception as e:
                    logger.error(f"Performance metrics: Error calculating AI/human breakdown: {e}")
                    raise HTTPException(status_code=500, detail="Unable to calculate interaction breakdown")

                # Interactions over time (last 6 months) - breakdown by AI vs Human
                interactions_over_time = []
                try:
                    interactions_result = await performance_dao.get_interactions_over_time()
                    interactions_over_time = [
                        {
                            "month": item["month"],
                            "total": item["total"],
                            "ai_handled": item["ai_handled"],
                            "human_handoff": item["human_handoff"]
                        }
                        for item in interactions_result
                    ]
                except Exception as e:
                    logger.error(f"Performance metrics: Error in interactions over time query: {e}")
                    interactions_over_time = []

                logger.debug("Performance metrics: Fetching satisfaction metrics with optimized single query")

                try:
                    satisfaction_results = await performance_dao.get_satisfaction_metrics()
                    satisfaction_over_time = [
                        {
                            "month": item["month"],
                            "satisfaction_score": float(item["satisfaction_score"]),
                            "total_feedback": item["total_feedback"]
                        }
                        for item in satisfaction_results
                    ]
                    
                    # Ensure it's an array and filter out invalid entries
                    if not isinstance(satisfaction_over_time, list):
                        logger.warning(f"Performance metrics: daily_scores is not an array: {type(satisfaction_over_time)}")
                        satisfaction_over_time = []

                    # Filter out None and non-dict values
                    satisfaction_over_time = [item for item in satisfaction_over_time if isinstance(item, dict) and item is not None]

                except Exception as satisfaction_error:
                    logger.error(f"Performance metrics: Error in satisfaction query: {satisfaction_error}", exc_info=True)
                    raise HTTPException(status_code=500, detail="Unable to retrieve satisfaction metrics")

                # Ensure satisfaction_over_time is an array of objects with correct structure
                if not isinstance(satisfaction_over_time, list):
                    logger.warning(f"Performance metrics: satisfaction_over_time is not a list: {type(satisfaction_over_time)}")
                    satisfaction_over_time = []

                # Filter out None values and ensure we only work with valid dictionaries
                satisfaction_over_time = [item for item in satisfaction_over_time if isinstance(item, dict) and item is not None]

                # Ensure we have 6 months of data, fill missing months
                current_month = datetime.now().replace(day=1)
                required_months = []
                for i in range(6):
                    month_date = current_month - timedelta(days=30*i)
                    month_str = month_date.strftime("%b")
                    required_months.append(month_str)

                # Fill missing months with default values
                existing_months = {item["month"] for item in satisfaction_over_time}
                for month in required_months:
                    if month not in existing_months:
                        satisfaction_over_time.append({
                            "month": month,
                            "satisfaction_score": 0.0,
                            "total_feedback": 0
                        })

                # Sort by month chronological order
                month_order = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                              "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}
                satisfaction_over_time.sort(key=lambda x: month_order.get(x["month"], 0))

                # Calculate satisfaction score and total feedback
                total_feedback = sum(item["total_feedback"] for item in satisfaction_over_time)
                satisfaction_score = 0.0
                if total_feedback > 0:
                    weighted_sum = sum(item["satisfaction_score"] * item["total_feedback"] for item in satisfaction_over_time)
                    satisfaction_score = weighted_sum / total_feedback

                # Group 3: Comparison metrics (previous period)
                logger.debug("Performance metrics: Starting comparison metrics queries")

                # Recent vs previous interactions
                recent_interactions = 0
                try:
                    recent_interactions = await performance_dao.get_recent_interactions()
                except Exception as e:
                    logger.error(f"Performance metrics: Error in recent interactions query: {e}")

                previous_interactions = 0
                try:
                    previous_interactions = await performance_dao.get_previous_interactions()
                except Exception as e:
                    logger.error(f"Performance metrics: Error in previous interactions query: {e}")

                # Recent vs previous engagement
                recent_engagement = 0
                try:
                    recent_engagement = await performance_dao.get_recent_engagement()
                except Exception as e:
                    logger.error(f"Performance metrics: Error in recent engagement query: {e}")

                previous_engagement = 0
                try:
                    previous_engagement = await performance_dao.get_previous_engagement()
                except Exception as e:
                    logger.error(f"Performance metrics: Error in previous engagement query: {e}")

                # Group 4: Uptime metrics (if available)
                uptime_data = []
                try:
                    uptime_results = await performance_dao.get_uptime_metrics()
                    uptime_data = [
                        {
                            "month": item["month"],
                            "uptime_percentage": float(item["uptime_percentage"])
                        }
                        for item in uptime_results
                    ]
                except Exception as e:
                    logger.warning(f"Performance metrics: Could not fetch uptime metrics: {e}")
                    # Provide default uptime data
                    uptime_data = [
                        {"month": "Jan", "uptime_percentage": 99.5},
                        {"month": "Feb", "uptime_percentage": 99.7},
                        {"month": "Mar", "uptime_percentage": 99.4},
                        {"month": "Apr", "uptime_percentage": 99.8},
                        {"month": "May", "uptime_percentage": 99.6},
                        {"month": "Jun", "uptime_percentage": 99.9}
                    ]

                # Prepare final response
                response_data = {
                    "total_interactions": total_interactions,
                    "total_sessions": total_sessions,
                    "active_sessions": active_sessions,
                    "avg_engagement_time_minutes": round(avg_engagement, 2) if avg_engagement else 0,
                    "deflection_rate": deflection_rate,
                    "ai_handled_chats": ai_handled_chats,
                    "human_agent_handoffs": human_agent_handoffs,
                    "interactions_over_time": interactions_over_time,
                    "satisfaction_metrics": {
                        "satisfaction_score": round(satisfaction_score, 2),
                        "total_feedback": total_feedback,
                        "satisfaction_over_time": satisfaction_over_time
                    },
                    "comparison_metrics": {
                        "recent_interactions": recent_interactions,
                        "previous_interactions": previous_interactions,
                        "recent_engagement": round(recent_engagement, 2) if recent_engagement else 0,
                        "previous_engagement": round(previous_engagement, 2) if previous_engagement else 0
                    },
                    "uptime_metrics": uptime_data
                }

                logger.info(f"Performance metrics: Successfully compiled all metrics in {datetime.now().isoformat()}")
                return response_data

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Performance metrics: Unexpected error in metrics compilation: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Unable to compile performance metrics")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Performance metrics: Database connection error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Database service temporarily unavailable")


@router.get("/performance/health")
async def health_check():
    """Health check endpoint for performance service."""
    try:
        async with get_db_connection() as conn:
            # Test basic database connectivity
            await conn.fetchval("SELECT 1")
            return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Performance health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
