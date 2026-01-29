from fastapi import APIRouter, HTTPException, Request

from chatbot_orchestration.core.logging_config import get_railway_logger
from chatbot_orchestration.core.utils import log_endpoint_request
from chatbot_orchestration.core.auth_middleware import require_auth

from ..schemas.models import ChatRequest
from ..service.chat_service import chat_service

logger = get_railway_logger(__name__)

router = APIRouter(tags=["Chat"])

@router.post("/chat/stream")
@require_auth()
async def chat_stream(request: Request, fastapi_request: Request, chat_request: ChatRequest):
    """
    Handle chat request with streaming response using optimized Pydantic AI Gateway Service.
    """
    try:
        # Get user data from request state (set by middleware)
        user_data = request.state.user
        
        log_endpoint_request("chatbot_orchestration", "chat_stream", fastapi_request)
        
        # Service handles all business logic
        return await chat_service.handle_chat_stream(chat_request, user_data)
        
    except Exception as e:
        logger.error(f"Error in chat stream: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")
