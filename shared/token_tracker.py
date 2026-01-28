"""
Token Usage Tracker
Tracks and accumulates token usage from Gemini API responses.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from shared.service.token_service import TokenService
from shared.logging_config import get_railway_logger
from shared.token_metrics import track_token_metrics

logger = get_railway_logger(__name__)

@dataclass
class TokenUsageData:
    """Data class for token usage information"""
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    provider: str = 'gemini'
    model: str = 'gemini-2.5-flash-lite'
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    api_call_type: str = 'rag'
    request_metadata: Optional[Dict[str, Any]] = None

# Global service instance for connection pooling
_token_service: Optional[TokenService] = None

def get_token_service() -> TokenService:
    """Get or create token service instance for connection pooling"""
    global _token_service
    if _token_service is None:
        _token_service = TokenService()
    return _token_service

async def log_async(message: str, level: str = "info") -> None:
    """Async logging to avoid blocking"""
    try:
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
    except Exception:
        pass  # Never let logging fail the main function

@track_token_metrics("track_token_usage")
async def track_token_usage(session_id: str, message_id: str, provider: str, model: str, 
                          prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                          api_call_type: str, request_metadata: Optional[Dict[str, Any]] = None) -> bool:
    """Track token usage using the TokenService
    
    Returns:
        bool: True if tracking succeeded, False otherwise
    """
    if not all(isinstance(x, int) and x >= 0 for x in [prompt_tokens, completion_tokens, total_tokens]):
        await log_async("Invalid token counts: must be non-negative integers", "error")
        raise ValueError("Invalid token counts: must be non-negative integers")
        
    try:
        token_service = get_token_service()  # Use pooled service instance
        await token_service.track_token_usage(
            session_id, message_id, provider, model,
            prompt_tokens, completion_tokens, total_tokens,
            api_call_type, request_metadata
        )
        await log_async(f"Token usage tracked for session {session_id}: {total_tokens} tokens")
        return True
    except ConnectionError as e:
        await log_async(f"Database connection error tracking token usage: {e}", "error")
        raise
    except Exception as e:
        await log_async(f"Unexpected error tracking token usage: {e}", "error")
        raise






@track_token_metrics("track_gemini_usage")
async def track_gemini_usage(prompt_tokens: int, candidates_tokens: int, session_id: Optional[str] = None, 
                          message_id: Optional[str] = None, api_call_type: str = 'rag', 
                          model: str = 'gemini-2.5-flash-lite') -> bool:
    """
    Track Gemini token usage and update llm_providers and token_usage_log tables.

    Args:
        prompt_tokens: Number of prompt tokens
        candidates_tokens: Number of candidate/output tokens
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
        
    Returns:
        bool: True if tracking succeeded, False otherwise
    """
    return await track_gemini_usage_detailed(
        prompt_tokens=prompt_tokens,
        completion_tokens=candidates_tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        session_id=session_id,
        message_id=message_id,
        api_call_type=api_call_type,
        model=model
    )


@track_token_metrics("track_gemini_usage_detailed")
async def track_gemini_usage_detailed(
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
    api_call_type: str = 'rag',
    model: str = 'gemini-2.5-flash-lite'
) -> bool:
    """Track detailed Gemini token usage using TokenService
    
    Returns:
        bool: True if tracking succeeded, False otherwise
    """
    # Validate input
    if not all(isinstance(x, int) and x >= 0 for x in [prompt_tokens, completion_tokens, total_tokens, cache_read_tokens, cache_write_tokens]):
        await log_async("Invalid token counts: must be non-negative integers", "error")
        raise ValueError("Invalid token counts: must be non-negative integers")
    
    # Calculate total if not provided
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens + cache_read_tokens + cache_write_tokens

    if total_tokens <= 0:
        await log_async("No tokens to track - skipping", "warning")
        return True  # Not an error, just nothing to track

    try:
        await log_async(f"Starting token tracking for session: {session_id}, message: {message_id}, total_tokens: {total_tokens}")
        
        token_service = get_token_service()  # Use pooled service instance
        
        # Use TokenService for both provider updates and detailed logging
        await token_service.track_token_usage(
            session_id=session_id,
            message_id=message_id,
            provider='gemini',
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            api_call_type=api_call_type,
            request_metadata={
                'cache_read_tokens': cache_read_tokens,
                'cache_write_tokens': cache_write_tokens
            }
        )
        
        await log_async(f"Successfully tracked Gemini usage: {total_tokens} tokens for session {session_id}")
        return True
        
    except ConnectionError as e:
        await log_async(f"Database connection error in detailed tracking: {e}", "error")
        raise
    except Exception as e:
        await log_async(f"Unexpected error in detailed tracking: {e}", "error")
        raise


@track_token_metrics("track_gemini_usage_from_response")
async def track_gemini_usage_from_response(usage_obj: Any, session_id: Optional[str] = None, 
                                         message_id: Optional[str] = None, api_call_type: str = 'rag', 
                                         model: str = 'gemini-2.5-flash-lite') -> bool:
    """
    Track Gemini token usage from API response usage object.
    
    Args:
        usage_obj: Gemini API response usage object
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
        
    Returns:
        bool: True if tracking succeeded, False otherwise
    """
    await log_async(f"Token tracking called for Gemini - session: {session_id}, message: {message_id}, type: {api_call_type}, model: {model}")

    if not usage_obj:
        await log_async("Gemini usage object is None or empty", "warning")
        return False

    try:
        # Extract detailed token breakdown from Gemini usage_metadata object
        prompt_tokens = (
            getattr(usage_obj, 'promptTokenCount', 0) or
            getattr(usage_obj, 'prompt_token_count', 0) or
            getattr(usage_obj, 'input_tokens', 0) or
            getattr(usage_obj, 'prompt_tokens', 0) or
            0
        )

        completion_tokens = (
            getattr(usage_obj, 'candidatesTokenCount', 0) or
            getattr(usage_obj, 'candidates_token_count', 0) or
            getattr(usage_obj, 'output_tokens', 0) or
            getattr(usage_obj, 'completion_tokens', 0) or
            0
        )

        total_tokens = (
            getattr(usage_obj, 'totalTokenCount', 0) or
            getattr(usage_obj, 'total_token_count', 0) or
            getattr(usage_obj, 'total_tokens', 0) or
            (prompt_tokens + completion_tokens)
        )

        cache_read_tokens = getattr(usage_obj, 'cache_read_tokens', 0) or 0
        cache_write_tokens = getattr(usage_obj, 'cache_write_tokens', 0) or 0

        if total_tokens > 0 or prompt_tokens > 0:
            return await track_gemini_usage_detailed(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                session_id=session_id,
                message_id=message_id,
                api_call_type=api_call_type,
                model=model
            )
        else:
            await log_async("No tokens found in Gemini usage object", "warning")
            return True
            
    except AttributeError as e:
        await log_async(f"Error extracting attributes from Gemini usage object: {e}", "error")
        raise
    except Exception as e:
        await log_async(f"Unexpected error extracting Gemini usage from response: {e}", "error")
        raise


@track_token_metrics("track_gemini_usage_with_db")
async def track_gemini_usage_with_db(run_usage: Any, session_id: Optional[str] = None, 
                                       message_id: Optional[str] = None, api_call_type: str = 'rag', 
                                       model: str = 'gemini-2.5-flash-lite', db_connection=None) -> bool:
    """
    Track Gemini token usage using an existing database connection.
    
    Args:
        run_usage: RunUsage object with token information
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
        db_connection: Existing database connection (optional)
        
    Returns:
        bool: True if tracking succeeded, False otherwise
    """
    try:
        # Extract token counts from RunUsage object
        prompt_tokens = getattr(run_usage, 'input_tokens', 0)
        completion_tokens = getattr(run_usage, 'output_tokens', 0)
        cache_read_tokens = getattr(run_usage, 'details', {}).get('accepted_prediction_tokens', 0)
        cache_write_tokens = getattr(run_usage, 'details', {}).get('rejected_prediction_tokens', 0)

        # Validate token counts
        if not all(isinstance(x, (int, float)) and x >= 0 for x in [prompt_tokens, completion_tokens, cache_read_tokens, cache_write_tokens]):
            await log_async("Invalid token counts in run_usage object", "error")
            raise ValueError("Invalid token counts in run_usage object")

        if prompt_tokens <= 0 and completion_tokens <= 0:
            await log_async("No tokens to track in run_usage object", "warning")
            return True

        total_tokens = int(prompt_tokens + completion_tokens + (cache_read_tokens or 0) + (cache_write_tokens or 0))

        # Use TokenService for consistency
        token_service = get_token_service()
        
        await token_service.track_token_usage(
            session_id=session_id,
            message_id=message_id,
            provider='gemini',
            model=model,
            prompt_tokens=int(prompt_tokens),
            completion_tokens=int(completion_tokens),
            total_tokens=total_tokens,
            api_call_type=api_call_type,
            request_metadata={
                'cache_read_tokens': int(cache_read_tokens or 0),
                'cache_write_tokens': int(cache_write_tokens or 0),
                'db_connection_provided': db_connection is not None
            }
        )

        await log_async(f"Successfully tracked Gemini usage with DB: {total_tokens} tokens for session {session_id}")
        return True
        
    except AttributeError as e:
        await log_async(f"Error extracting attributes from run_usage object: {e}", "error")
        raise
    except ValueError as e:
        await log_async(f"Validation error in track_gemini_usage_with_db: {e}", "error")
        raise
    except Exception as e:
        await log_async(f"Unexpected error tracking Gemini usage with provided DB: {e}", "error")
        raise

