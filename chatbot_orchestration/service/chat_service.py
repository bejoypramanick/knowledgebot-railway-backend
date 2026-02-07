"""
Chat Service Layer for Chatbot Orchestration
Provides business logic for chat operations
"""
import asyncio
import json
import uuid

from fastapi.responses import StreamingResponse

from shared.otel_logger import get_otel_logger
from chatbot_orchestration.core.token_tracker import track_gemini_usage_from_response

from ..agent.prompt import get_system_prompt
from ..core.dependencies import ChatSessionDeps
from ..service.agent_service import pydantic_ai_service, session_state_manager
from ..tools.general import (query_railway_postgres,
                             request_human_agent_connection)
from ..tools.rag import search_knowledge_base
from ..dao.session_persistence_dao import SessionPersistenceDAO

logger = get_otel_logger("chat_service", "chatbot-orchestration")

# Pydantic AI imports for processing messages

class ChatService:
    """Service layer for chat operations"""

    def __init__(self):
        self.persistence_dao = SessionPersistenceDAO()
    
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
        """Generate streaming response with retry logic and message persistence"""
        max_retries = 3
        retry_delay = 1.0
        session_db_id = None

        try:
            # Get or create session in database
            session_db_id = await self.persistence_dao.get_or_create_session(session_id)

            # Save user message to database
            try:
                await self.persistence_dao.save_user_message(session_db_id, message)
                logger.info(f"💬 Saved user message for session {session_id}")
            except Exception as e:
                logger.error(f"⚠️ Failed to save user message: {e}")
                # Continue processing even if message save fails

        except Exception as e:
            logger.error(f"❌ Failed to initialize session persistence: {e}")
            # Continue with streaming response even if persistence setup fails

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

                # Save bot response to database
                if session_db_id:
                    try:
                        await self.persistence_dao.save_bot_message(session_db_id, response_text, 'bot')
                        logger.info(f"🤖 Saved bot response for session {session_id}")
                    except Exception as e:
                        logger.error(f"⚠️ Failed to save bot message: {e}")
                        # Continue streaming even if save fails

                # Stream the response
                yield f"data: {json.dumps({'type': 'content', 'content': response_text})}\n\n"
                yield f"data: {json.dumps({'type': 'end', 'content': ''})}\n\n"

                # Track token usage if available
                if hasattr(result, 'usage') or hasattr(result, 'token_usage'):
                    await self._track_token_usage(result, session_id)

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
    
    async def _track_token_usage(self, result, session_id: str):
        """Track token usage from result"""
        try:
            # Extract token usage information
            usage_data = None
            if hasattr(result, 'usage'):
                usage_data = result.usage
            elif hasattr(result, 'token_usage'):
                usage_data = result.token_usage
            
            if usage_data:
                # Use TokenService for both provider updates and detailed logging
                from ..dao.token_dao import TokenDAO
                token_dao = TokenDAO()
                
                # Generate a message ID if not available
                import uuid
                message_id = str(uuid.uuid4())
                
                # Extract token counts from usage data
                prompt_tokens = getattr(usage_data, 'promptTokenCount', 0) or getattr(usage_data, 'prompt_tokens', 0)
                completion_tokens = getattr(usage_data, 'candidatesTokenCount', 0) or getattr(usage_data, 'completion_tokens', 0)
                total_tokens = getattr(usage_data, 'totalTokenCount', 0) or getattr(usage_data, 'total_tokens', 0)
                
                # Save to database using DAO
                import os
                model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")
                
                success = await token_dao.save_token_usage(
                    session_id=session_id,
                    message_id=message_id,
                    provider='gemini',
                    model=model_name,
                    prompt_tokens=int(prompt_tokens),
                    completion_tokens=int(completion_tokens),
                    total_tokens=int(total_tokens),
                    api_call_type='rag'
                )
                
                if success:
                    logger.info(f"✅ Tracked token usage: {total_tokens} tokens for session {session_id}")
                else:
                    logger.error(f"❌ Failed to track token usage for session {session_id}")
                    
        except Exception as e:
            logger.error(f"Error tracking token usage: {e}")
    
    def _create_error_stream(self, error_message: str):
        """Create error streaming response"""
        return StreamingResponse(
            iter(["data: " + json.dumps({"error": error_message}) + "\n\n"]),
            media_type="text/plain",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
        )

    async def get_chat_history(self, session_id: str):
        """Get chat history for a session"""
        try:
            # This would need to be implemented based on the actual chat storage
            # For now, return empty history
            return {
                "session_id": session_id,
                "messages": [],
                "total_messages": 0
            }
        except Exception as e:
            logger.error(f"Error getting chat history for session {session_id}: {e}")
            raise

    async def delete_session(self, session_id: str):
        """Delete a chat session"""
        try:
            # This would need to be implemented based on the actual chat storage
            # For now, return success
            logger.info(f"Deleted session: {session_id}")
            return {"success": True, "message": "Session deleted successfully"}
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            raise

    async def get_all_sessions(self):
        """Get all chat sessions"""
        try:
            # This would need to be implemented based on the actual chat storage
            # For now, return empty list
            return {
                "sessions": [],
                "total_sessions": 0
            }
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            raise

# Singleton instance
chat_service = ChatService()
