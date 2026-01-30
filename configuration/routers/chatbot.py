from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from configuration.core.logging_config import get_railway_logger
from configuration.core.utils import log_endpoint_request

from ..schemas.models import ChatbotConfigRequest
from ..service.configuration_service import configuration_service
from ..service.auth_service import AuthService
from ..utils.logging_utils import log_configuration_change
from ..utils.validation import validate_configuration_consistency

logger = get_railway_logger(__name__)
auth_service = AuthService()

router = APIRouter(prefix="/api/v1", tags=["Chatbot Configuration"])

@router.get("/configuration/chatbot")
async def get_chatbot_config(request: Request):
    """Get chatbot configuration"""
    try:
        config = await configuration_service.get_chatbot_config()
        return config
    except Exception as e:
        logger.error(f"Error fetching configuration: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching configuration: {str(e)}")


@router.post("/configuration/chatbot")
async def save_chatbot_config(
    config: ChatbotConfigRequest,
    request: Request
):
    """Save chatbot configuration"""
    try:
        # Validate configuration consistency
        validation_result = validate_configuration_consistency(config)
        if not validation_result.is_valid:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Configuration validation failed",
                    "issues": validation_result.issues
                }
            )

        # Handle admin emails - sync with database
        if config.admin_emails is not None:
            admin_emails_list = []
            for admin_item in config.admin_emails:
                email = None
                if isinstance(admin_item, dict):
                    email = admin_item.get('email', '')
                elif hasattr(admin_item, 'email'):
                    email = admin_item.email
                elif isinstance(admin_item, str):
                    email = admin_item
                
                if email and email.strip():
                    admin_emails_list.append(email.strip())
            
            if admin_emails_list:
                admin_sync_result = await configuration_service.sync_admin_emails(admin_emails_list)
                logger.info(f"Admin sync result: {admin_sync_result}")

        # Handle human agents - sync with database
        if config.human_agents is not None:
            human_agents_list = [email.strip() for email in config.human_agents if email and email.strip()]
            
            if human_agents_list:
                agent_sync_result = await configuration_service.sync_human_agent_emails(human_agents_list)
                logger.info(f"Human agent sync result: {agent_sync_result}")

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

        # Log the configuration change (non-blocking)
        try:
            await log_configuration_change(
                user_email=request.headers.get('X-User-Email', 'system'),
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
    session_id: str
):
    """Request a human agent for a chat session."""
    # Note: Authentication should be handled at the API Gateway level
    try:
        log_endpoint_request("configuration_service", "request-agent", None)
        result = await configuration_service.request_human_agent(session_id)
        return result
    except Exception as e:
        logger.error(f"Error requesting human agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error requesting human agent: {str(e)}")
