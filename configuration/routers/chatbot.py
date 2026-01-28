from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import List, Union
import logging

from ..schemas.models import ChatbotConfigRequest, AdminAccount, ValidatedEmail
from ..utils.validation import validate_configuration_consistency
from ..utils.logging_utils import log_configuration_change
from ..service.configuration_service import configuration_service
from shared.auth_middleware import get_current_user
from shared.utils import log_endpoint_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Chatbot Configuration"])

@router.get("/configuration/chatbot")
async def get_chatbot_config():
    """Get chatbot configuration"""
    try:
        # Service handles all data transformation
        data = await configuration_service.get_chatbot_config()
        
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

        # Use service for admin checks
        from ..service.auth_service import AuthService
        auth_service = AuthService()

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
                    is_admin = await auth_service.check_admin_exists(email)
                    if not is_admin:
                        await auth_service.add_admin(email)
                        logger.info(f"Admin {email} added to database")

        # Handle human agents
        if config.human_agents is not None:
            for agent_email in config.human_agents:
                if agent_email and isinstance(agent_email, str):
                    try:
                        await configuration_service.add_human_agent(agent_email)
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
                await configuration_service.upsert_configuration_metadata(meta_updates)

            # Update notification settings
        if config.notifications:
            if config.notifications.user_interactions_enabled is not None:
                await configuration_service.upsert_notification_setting_with_desc(
                    'user_interactions_enabled', 
                    config.notifications.user_interactions_enabled,
                    'Enable notifications for user interactions'
                )

            if config.notifications.error_alerts_enabled is not None:
                await configuration_service.upsert_notification_setting_with_desc(
                    'error_alerts_enabled',
                    config.notifications.error_alerts_enabled,
                    'Enable error alert notifications'
                )

            if config.notifications.feedback_requests_enabled is not None:
                await configuration_service.upsert_notification_setting_with_desc(
                    'feedback_requests_enabled',
                    config.notifications.feedback_requests_enabled,
                    'Enable feedback request notifications'
                )

            # Update security settings
        if config.security:
            if config.security.response_timeout is not None:
                await configuration_service.upsert_security_setting_with_desc(
                    'response_timeout',
                    str(config.security.response_timeout),
                    'integer',
                    'Response timeout in seconds'
                )

            if config.security.remove_pii is not None:
                await configuration_service.upsert_security_setting_with_desc(
                    'remove_pii',
                    str(config.security.remove_pii).lower(),
                    'boolean',
                    'Remove personally identifiable information'
                )

            if config.security.restrict_config is not None:
                await configuration_service.upsert_security_setting_with_desc(
                    'restrict_config',
                    str(config.security.restrict_config).lower(),
                    'boolean',
                    'Restrict configuration access'
                )

        # Update persona configuration
        if config.persona:
            if config.persona.selected_persona and config.persona.system_prompt:
                await configuration_service.upsert_persona(config.persona.selected_persona, config.persona.system_prompt)

        # Update LLM provider configurations
        if config.llm_tokens:
            for provider, data in config.llm_tokens.items():
                token_limit = data.get("limit")
                token_used = data.get("used")
                if token_limit is not None:
                    await configuration_service.update_llm_tokens(provider, token_limit)
                if token_used is not None:
                    await configuration_service.update_llm_used_tokens(provider, token_used)
            
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
                    existing = await configuration_service.find_human_agent(email)

                    if existing:
                        logger.info(f"Agent {email} already exists, skipping creation")
                        continue

                    # Create new agent
                    logger.info(f"Creating new agent record for {email}")
                    agent_id = await configuration_service.add_human_agent(email)

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
                current_agents = await configuration_service.get_all_human_agents()
                
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
                        await configuration_service.delete_human_agent(email)
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
        result = await configuration_service.request_human_agent(session_id)
        return result
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")
