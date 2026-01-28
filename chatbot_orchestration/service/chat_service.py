"""
Chat Service Layer for Chatbot Orchestration
Provides business logic for chat operations
"""
import asyncio
import json
import uuid

from fastapi.responses import StreamingResponse

from shared.logging_config import get_railway_logger
from shared.token_tracker import track_gemini_usage_from_response

from ..agent.prompt import get_system_prompt
from ..core.dependencies import ChatSessionDeps
from ..service.agent_service import pydantic_ai_service, session_state_manager
from ..tools.general import (query_railway_postgres,
                             request_human_agent_connection)
from ..tools.rag import search_knowledge_base

# Pydantic AI imports for processing messages

logger = get_railway_logger(__name__)

class ChatService:
    """Service layer for chat operations"""
    
    def __init__(self):
        pass  # Service manages its own dependencies
    
    async def handle_chat_stream(self, request):
        """Handle chat request with streaming response using optimized Pydantic AI Gateway Service."""
        try:
            session_id = request.session_id or str(uuid.uuid4())
            
            # Generate system prompt with caching
            system_prompt = get_system_prompt(
                custom_prompt=request.system_prompt,
                response_policy=request.response_policy
            )
            
            # Prepare tools for the agent
            tools = self._prepare_tools()
            
            # Create optimized agent using Pydantic AI Gateway Service
            agent = await self._create_agent(session_id, system_prompt, tools)
            
            if not agent:
                logger.error("Failed to create agent")
                return self._create_error_stream("Failed to create agent")
            
            # Prepare message history
            message_history = self._prepare_message_history(session_id)
            session_dep = ChatSessionDeps(session_id=session_id)
            
            logger.info(f"🚀 Starting optimized chat stream for session {session_id}")
            
            # Generate streaming response
            return StreamingResponse(
                self._generate_response_stream(agent, request.message, session_dep, session_id),
                media_type="text/plain",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )
            
        except Exception as e:
            logger.error(f"Error in chat stream: {e}", exc_info=True)
            return self._create_error_stream("Internal server error")
    
    def _prepare_tools(self):
        """Prepare tools for the agent"""
        tools = [search_knowledge_base]
        tools.append(request_human_agent_connection)
        tools.append(query_railway_postgres)  # It handles internal check
        return tools
    
    async def _create_agent(self, session_id: str, system_prompt: str, tools: list):
        """Create optimized agent using Pydantic AI Gateway Service"""
        try:
            agent = await pydantic_ai_service.create_agent(
                session_id=session_id,
                system_prompt=system_prompt,
                tools=tools
            )
            return agent
        except Exception as e:
            logger.error(f"❌ Failed to create optimized agent: {e}")
            logger.error("❌ No fallback available - agent creation failed")
            return None
    
    def _prepare_message_history(self, session_id: str):
        """Prepare message history for the session"""
        message_history = []
        turn_count = session_state_manager.get_turn_count(session_id)
        is_new_session = session_state_manager.is_new_session(session_id)
        
        if not is_new_session:
            message_history = session_state_manager.get_message_history(session_id)
            logger.info(f"📚 Using preserved message history for turn {turn_count + 1}: {len(message_history)} messages")
        else:
            logger.info(f"🆕 Starting new session (turn 1) for {session_id}")
        
        return message_history
    
    async def _generate_response_stream(self, agent, message: str, session_dep, session_id: str):
        """Generate streaming response with retry logic"""
        max_retries = 3
        retry_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                if attempt == 0:
                    yield f"data: {json.dumps({'type': 'start', 'content': ''})}\n\n"
                
                result = await pydantic_ai_service.run_agent_with_fallback(
                    agent,
                    message,
                    session_dep
                )
                
                session_state_manager.update_session_state(session_id, result)
                
                response_text = self._extract_response_text(result)
                
                # Stream the response
                yield f"data: {json.dumps({'type': 'content', 'content': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'end', 'content': ''})}\n\n"
                
                # Track token usage if available
                if hasattr(result, 'usage') or hasattr(result, 'token_usage'):
                    self._track_token_usage(result, session_id)
                
                break
                
            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    yield f"data: {json.dumps({'type': 'error', 'content': 'Failed to process request after retries'})}\n\n"
                else:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
    
    def _extract_response_text(self, result):
        """Extract response text from result object"""
        response_text = ""
        if hasattr(result, 'output'):
            response_text = result.output if isinstance(result.output, str) else str(result.output)
        elif hasattr(result, 'data'):
            response_text = str(result.data)
        elif hasattr(result, 'response') and result.response:
            response_text = result.response.text if hasattr(result.response, 'text') else str(result.response)
        return response_text
    
    def _track_token_usage(self, result, session_id: str):
        """Track token usage from result"""
        try:
            # Extract token usage information
            usage_data = None
            if hasattr(result, 'usage'):
                usage_data = result.usage
            elif hasattr(result, 'token_usage'):
                usage_data = result.token_usage
            
            if usage_data:
                # This would need to be adapted based on the actual structure
                track_gemini_usage_from_response(
                    session_id=session_id,
                    response=result
                )
        except Exception as e:
            logger.error(f"Error tracking token usage: {e}")
    
    def _create_error_stream(self, error_message: str):
        """Create error streaming response"""
        return StreamingResponse(
            iter(["data: " + json.dumps({"error": error_message}) + "\n\n"]),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

# Singleton instance
chat_service = ChatService()
