from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import List, Union
import logging

from ..core.database import get_db_connection
from ..schemas.models import ChatbotConfigRequest, AdminAccount, ValidatedEmail
from ..utils.validation import validate_configuration_consistency
from ..utils.logging_utils import log_configuration_change
from ..servcie.configuration_service import configuration_service
from shared.auth_middleware import get_current_user
from shared.utils import log_endpoint_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Chatbot Configuration"])

@router.get("/configuration/chatbot")
async def get_chatbot_config():
    """Get chatbot configuration"""
    try:
        # Read from new normalized tables
        # Get configuration metadata
        metadata = await configuration_service.get_metadata()

        # Get notification settings
        notification_rows = await configuration_service.get_notification_settings()

        # Get security settings
        security_rows = await configuration_service.get_security_settings()

        # Get LLM providers
        llm_rows = await configuration_service.get_llm_providers()

        # Get active persona
        persona = await configuration_service.get_active_persona()

        # Fetch human agents
        human_agents_list = await configuration_service.get_human_agents()
        logger.info(f"Fetched {len(human_agents_list)} human agent(s)")

        # Fetch admins
        admin_emails_list = await configuration_service.get_admins()
        logger.info(f"Fetched {len(admin_emails_list)} admin(s)")

        # Build notification settings dict
        notifications = {
            "user_interactions_enabled": False,
            "error_alerts_enabled": False,
            "feedback_requests_enabled": True
        }
        for row in notification_rows:
            if row['setting_name'] == 'user_interactions_enabled':
                notifications['user_interactions_enabled'] = row['is_enabled']
            elif row['setting_name'] == 'error_alerts_enabled':
                notifications['error_alerts_enabled'] = row['is_enabled']
            elif row['setting_name'] == 'feedback_requests_enabled':
                notifications['feedback_requests_enabled'] = row['is_enabled']

        # Build security settings dict
        security = {
            "response_timeout": 30,
            "remove_pii": False,
            "restrict_config": False
        }
        for row in security_rows:
            if row['setting_name'] == 'response_timeout':
                security['response_timeout'] = int(row['setting_value']) if row['setting_type'] == 'integer' else 30
            elif row['setting_name'] == 'remove_pii':
                security['remove_pii'] = row['setting_value'].lower() == 'true' if row['setting_type'] == 'boolean' else False
            elif row['setting_name'] == 'restrict_config':
                security['restrict_config'] = row['setting_value'].lower() == 'true' if row['setting_type'] == 'boolean' else False

        # Build LLM tokens dict
        llm_tokens = {
            "gemini": {"used": 0, "available": 20000, "limit": 20000}
        }
        for row in llm_rows:
            provider = row['provider_name']
            if provider == 'gemini':
                llm_tokens['gemini'] = {
                    "used": row['token_used'] or 0,
                    "available": (row['token_limit'] or 0) - (row['token_used'] or 0),
                    "limit": row['token_limit'] or 0
                }

            # Build persona dict
            persona_config = {
                "system_prompt": persona['system_prompt'] if persona else "",
                "selected_persona": persona['persona_name'] if persona else "friendly-receptionist"
            }

            # Build final configuration
            data = {
                "admin_user": "GLOBISTAAN",
                "admin_emails": admin_emails_list,
                "admin_password": "**********",
                "human_agents": human_agents_list,
                "hil_enabled": metadata['hil_enabled'] if metadata else True,
                "notifications": notifications,
                "security": security,
                "response_policy": metadata['response_policy'] if metadata else 30,
                "data_management": {
                    "backup_logs": False  # This was removed from old schema, keeping default
                },
                "persona": persona_config,
                "llm_tokens": llm_tokens
            }
            response = JSONResponse(content=data)
            # Add cache headers for faster loading (5 seconds cache, but allow revalidation)
            response.headers["Cache-Control"] = "public, max-age=5, must-revalidate"
            return response
    except Exception as e:
        logger.error(f"Error fetching chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching configuration: {str(e)}")


@router.post("/configuration/chatbot")
async def save_chatbot_config(
    config: ChatbotConfigRequest,
    current_user: dict = Depends(get_current_user),
    request: Request = None
):
    """Save chatbot configuration"""
    try:
        # Validate business logic
        business_errors = validate_configuration_consistency(config)
        if business_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Business logic validation failed: {'; '.join(business_errors)}"
            )

        async with get_db_connection() as conn:
                from .dao.auth_dao import AuthDAO
                auth_dao = AuthDAO(conn)

                # Handle admin emails
                if config.admin_emails is not None:
                    for admin_item in config.admin_emails:
                        email = None
                        if isinstance(admin_item, dict):
                            email = admin_item.get('email', '')
                        elif hasattr(admin_item, 'email'):
                            email = admin_item.email
                        elif isinstance(admin_item, str):
                            email = admin_item
                        
                        if email:
                            try:
                                await dao.add_admin(email)
                                logger.info(f"Admin {email} added to database")
                            except Exception as e:
                                logger.error(f"Error adding admin {email}: {e}")

                # Handle human agents
                if config.human_agents is not None:
                    for agent_email in config.human_agents:
                        if agent_email and isinstance(agent_email, str):
                            try:
                                await dao.add_human_agent(agent_email)
                                logger.info(f"Human agent {agent_email} added directly")
                            except Exception as e:
                                logger.error(f"Error processing human agent {agent_email}: {e}")

            # Update configuration metadata
            if any([config.hil_enabled is not None, config.response_policy is not None]):
                meta_updates = {}
                if config.hil_enabled is not None:
                    meta_updates['hil_enabled'] = config.hil_enabled
                if config.response_policy is not None:
                    meta_updates['response_policy'] = config.response_policy
                
                if meta_updates:
                    await dao.upsert_configuration_metadata(meta_updates)

            # Update notification settings
            if config.notifications:
                if config.notifications.user_interactions_enabled is not None:
                    await dao.upsert_notification_setting_with_desc(
                        'user_interactions_enabled', 
                        config.notifications.user_interactions_enabled,
                        'Enable notifications for user interactions'
                    )

                if config.notifications.error_alerts_enabled is not None:
                    await dao.upsert_notification_setting_with_desc(
                        'error_alerts_enabled',
                        config.notifications.error_alerts_enabled,
                        'Enable error alert notifications'
                    )

                if config.notifications.feedback_requests_enabled is not None:
                    await dao.upsert_notification_setting_with_desc(
                        'feedback_requests_enabled',
                        config.notifications.feedback_requests_enabled,
                        'Enable feedback request notifications'
                    )

            # Update security settings
            if config.security:
                if config.security.response_timeout is not None:
                    await dao.upsert_security_setting_with_desc(
                        'response_timeout',
                        str(config.security.response_timeout),
                        'integer',
                        'Response timeout in seconds'
                    )

                if config.security.remove_pii is not None:
                    await dao.upsert_security_setting_with_desc(
                        'remove_pii',
                        str(config.security.remove_pii).lower(),
                        'boolean',
                        'Remove personally identifiable information'
                    )

                if config.security.restrict_config is not None:
                    await dao.upsert_security_setting_with_desc(
                        'restrict_config',
                        str(config.security.restrict_config).lower(),
                        'boolean',
                        'Restrict configuration access'
                    )

            # Update persona configuration
            if config.persona:
                if config.persona.selected_persona and config.persona.system_prompt:
                    await dao.upsert_persona(config.persona.selected_persona, config.persona.system_prompt)

            # Update LLM provider configurations
            if config.llm_tokens:
                for provider, data in config.llm_tokens.items():
                    token_limit = data.get("limit")
                    token_used = data.get("used")
                    if token_limit is not None:
                        await dao.update_llm_tokens(provider, token_limit)
                    if token_used is not None:
                        await dao.update_llm_used_tokens(provider, token_used)
            
            # Configuration updates completed using normalized tables
            logger.info("Configuration saved successfully using normalized tables")
            
            # If human agents are provided, process them
            logger.info(f"Checking human agents: config.human_agents = {config.human_agents}")
            if config.human_agents is not None and len(config.human_agents) > 0:
                logger.info(f"Processing {len(config.human_agents)} human agent(s)")
                try:
                    agents_created = []
                    
                    for email in config.human_agents:
                        if not email or not email.strip():
                            continue
                        
                        email = email.strip()
                        
                        # Check if agent already exists
                        existing = await dao.find_human_agent(email)

                        if existing:
                            logger.info(f"Agent {email} already exists, skipping creation")
                            continue

                        # Create new agent
                        logger.info(f"Creating new agent record for {email}")
                        agent_id = await conn.fetchval(
                            """
                            INSERT INTO human_agents (email)
                            VALUES ($1)
                            RETURNING id::text
                            """,
                            email
                        )

                        agents_created.append({
                            "email": email
                        })
                        logger.info(f"✅ Human agent {email} added directly")
                except Exception as e:
                    # Don't fail the entire save if agent processing fails
                    logger.error(f"❌ Error processing human agents: {e}", exc_info=True)
                    logger.error(f"Error type: {type(e).__name__}")
            
            # Handle deletion of agents that are no longer in the list
            if config.human_agents is not None:
                try:
                    # Get all current agents from the database
                    current_agents = await conn.fetch(
                        "SELECT email FROM human_agents"
                    )
                    
                    # Create a mapping of lowercase email to original email for comparison
                    current_emails_map = {agent['email'].lower(): agent['email'] for agent in current_agents}
                    
                    # Get the new list of emails (normalize to lowercase for comparison)
                    new_emails_lower = {email.strip().lower() for email in config.human_agents if email and email.strip()}
                    
                    # Find agents to delete (in database but not in new list)
                    agents_to_delete = []
                    for lower_email, original_email in current_emails_map.items():
                        if lower_email not in new_emails_lower:
                            agents_to_delete.append(original_email)
                    
                    # Delete agents that are no longer in the list
                    if agents_to_delete:
                        logger.info(f"Deleting {len(agents_to_delete)} agent(s) that are no longer in the list: {', '.join(agents_to_delete)}")
                        for email in agents_to_delete:
                            await conn.execute(
                                "DELETE FROM human_agents WHERE email = $1",
                                email
                            )
                            logger.info(f"✅ Deleted agent {email} from database")
                    else:
                        logger.info("No agents to delete - all current agents are in the new list")
                except Exception as e:
                    # Don't fail the entire save if deletion fails
                    logger.error(f"❌ Error deleting removed human agents: {e}", exc_info=True)
            else:
                logger.info("No human agents provided or list is empty, skipping agent processing")

            # Log the configuration change (non-blocking)
            try:
                await log_configuration_change(
                    user_email=current_user.get('email'),
                    action='chatbot_config_update',
                    details=config.dict(exclude_unset=True),
                    ip_address=request.client.host if request else None
                )
            except Exception as e:
                logger.warning(f"Failed to log configuration change: {e}")
                # Don't fail the configuration save if logging fails

            return {"success": True, "message": "Configuration saved successfully"}
    except Exception as e:
        logger.error(f"Error saving chatbot configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving configuration: {str(e)}")

@router.post("/admin/chat-sessions/{session_id}/request-agent")
async def request_human_agent(
    session_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Request a human agent for a chat session."""
    try:
        log_endpoint_request("configuration_service", "request-agent", None)
        
        async with get_db_connection() as conn:
            # Get session details
            session = await conn.fetchrow(
                "SELECT * FROM chat_sessions WHERE session_id = $1",
                session_id
            )
            
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            
            # Check if agent is already assigned
            existing_assignment = await conn.fetchrow(
                """
                SELECT ha.* FROM human_agents ha
                JOIN agent_session_assignments asa ON ha.id = asa.agent_id
                WHERE asa.session_id = $1 AND asa.status = 'active'
                """,
                session_id
            )
            
            if existing_assignment:
                return {
                    "status": "already_assigned",
                    "agent": {
                        "id": existing_assignment['id'],
                        "email": existing_assignment['email'],
                        "name": existing_assignment['name']
                    }
                }
            
            # Find available agents
            available_agents = await conn.fetch(
                """
                SELECT * FROM human_agents 
                WHERE is_active = true 
                AND is_online = true
                ORDER BY last_activity DESC
                LIMIT 5
                """
            )
            
            if not available_agents:
                return {
                    "status": "no_agents_available",
                    "message": "No human agents are currently available"
                }
            
            # Assign first available agent
            agent = available_agents[0]
            
            # Create assignment record
            await conn.execute(
                """
                INSERT INTO agent_session_assignments 
                (session_id, agent_id, status, assigned_at, assigned_by)
                VALUES ($1, $2, 'active', NOW(), $3)
                ON CONFLICT (session_id) DO UPDATE SET 
                status = 'active', agent_id = $2, assigned_at = NOW()
                """,
                session_id, agent['id'], current_user.get('email', 'system')
            )
            
            return {
                "status": "assigned",
                "agent": {
                    "id": agent['id'],
                    "email": agent['email'],
                    "name": agent['name']
                }
            }
            
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")
