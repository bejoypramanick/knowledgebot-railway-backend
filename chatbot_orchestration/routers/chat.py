from shared.logging_config import get_railway_logger
import logging
from fastapi import APIRouter, HTTPException, Request

from ..schemas.models import ChatRequest
from ..servce.chat_service import chat_service
from shared.utils import log_endpoint_request

logger = get_railway_logger(__name__)

router = APIRouter(tags=["Chat"])

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Handle chat request with streaming response using optimized Pydantic AI Gateway Service.
    """
    try:
        log_endpoint_request("chatbot_orchestration", "chat_stream", None)
        
        # Service handles all business logic
        return await chat_service.handle_chat_stream(request)
        
    except Exception as e:
        logger.error(f"Error in chat stream: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat request: {str(e)}")
