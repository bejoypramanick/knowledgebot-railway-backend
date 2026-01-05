"""
Configuration API Endpoints for Railway Backend
Handles chatbot and widget configuration management
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import logging
from contextlib import asynccontextmanager

# Import shared database utilities
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db

logger = logging.getLogger(__name__)

# Configuration Router
config_router = APIRouter(prefix="/api/v1/configuration", tags=["configuration"])

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

class ChatbotConfigRequest(BaseModel):
    human_agents: Optional[List[str]] = None
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
    """Get database connection from shared pool"""
    if not railway_db or not railway_db._pool:
        raise HTTPException(status_code=503, detail="Database not initialized")
    async with railway_db.acquire() as conn:
        yield conn


# Chatbot Configuration Endpoints
@config_router.get("/chatbot")
async def get_chatbot_config():
    """Get chatbot configuration"""
    try:
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT 
                    admin_user,
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
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            
            if not row:
                # Return default configuration
                return {
                    "admin_user": "GLOBISTAAN",
                    "admin_password": "**********",
                    "human_agents": [],
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
            
            return {
                "admin_user": row["admin_user"],
                "admin_password": "**********",
                "human_agents": row["human_agents"] or [],
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
                    "deepseek": {
                        "used": row["llm_token_used_deepseek"],
                        "available": row["llm_token_limit_deepseek"] - row["llm_token_used_deepseek"],
                        "limit": row["llm_token_limit_deepseek"]
                    }
                }
            }
    except Exception as e:
        logger.error(f"Error fetching chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching configuration: {str(e)}")


@config_router.post("/chatbot")
async def save_chatbot_config(config: ChatbotConfigRequest):
    """Save chatbot configuration"""
    try:
        async with get_db_connection() as conn:
            # Build update query dynamically based on provided fields
            updates = []
            values = []
            param_index = 1
            
            if config.human_agents is not None:
                updates.append(f"human_agents = ${param_index}")
                values.append(config.human_agents)
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
            query = f"""
                INSERT INTO chatbot_configuration (admin_user, {', '.join([u.split(' = ')[0] for u in updates])})
                VALUES ('GLOBISTAAN', {', '.join([f'${i+1}' for i in range(len(updates))])})
                ON CONFLICT (admin_user) 
                DO UPDATE SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
            """
            
            await conn.execute(query, *values)
            
            return {"success": True, "message": "Configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving configuration: {str(e)}")


# Widget Configuration Endpoints
@config_router.get("/widget")
async def get_widget_config():
    """Get widget configuration"""
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
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            
            if not row:
                # Return default configuration
                return {
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
            
            return {
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
    except Exception as e:
        logger.error(f"Error fetching widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching widget configuration: {str(e)}")


@config_router.post("/widget")
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
            
            # Use INSERT ... ON CONFLICT to handle upsert (assuming single row)
            query = f"""
                INSERT INTO widget_configuration (id, {', '.join([u.split(' = ')[0] for u in updates])})
                VALUES (1, {', '.join([f'${i+1}' for i in range(len(updates))])})
                ON CONFLICT (id) 
                DO UPDATE SET {', '.join(updates)}, updated_at = CURRENT_TIMESTAMP
            """
            
            await conn.execute(query, *values)
            
            return {"success": True, "message": "Widget configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving widget configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving widget configuration: {str(e)}")

