"""
Streaming Service for Chatbot Orchestration
Handles streaming responses and message formatting
"""

import json
import asyncio
from typing import Any, Dict, List, AsyncGenerator

from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
from shared.otel_logger import get_otel_logger

from ..core.dependencies import ChatSessionDeps
from .session_manager import session_state_manager

logger = get_otel_logger("streaming_service", "chatbot-orchestration")

class StreamingService:
    """Handles streaming responses for the chatbot."""

    def __init__(self):
        pass

    def _convert_db_messages_to_pydantic_ai(self, db_messages: List[Dict[str, Any]]) -> List[Any]:
        """Convert database messages to Pydantic AI message format."""
        pydantic_messages = []
        
        for msg in db_messages:
            try:
                if msg.get('role') == 'user':
                    # Convert user message
                    user_msg = ModelRequest(
                        parts=[UserPromptPart(content=msg.get('content', ''))]
                    )
                    pydantic_messages.append(user_msg)
                    logger.debug(f"🔄 Converted user message: {msg.get('content', '')[:50]}...")
                    
                elif msg.get('role') == 'assistant':
                    # Convert assistant message
                    assistant_msg = ModelResponse(
                        parts=[TextPart(content=msg.get('content', ''))]
                    )
                    pydantic_messages.append(assistant_msg)
                    logger.debug(f"🔄 Converted assistant message: {msg.get('content', '')[:50]}...")
                    
            except Exception as e:
                logger.warning(f"⚠️ Failed to convert message: {e}")
                logger.warning(f"⚠️ Message data: {msg}")
                continue
        
        logger.info(f"✅ Converted {len(pydantic_messages)} messages to Pydantic AI format")
        return pydantic_messages

    async def stream_agent_response(
        self, 
        agent, 
        message: str, 
        session_id: str, 
        user_email: str = "anonymous@example.com"
    ) -> AsyncGenerator[str, None]:
        """Stream agent response with proper formatting and error handling."""
        
        try:
            logger.info(f"🚀 Starting agent stream for session: {session_id}")
            logger.info(f"📝 Message: {message[:100]}...")

            # Update session activity
            session_state_manager.update_session_activity(session_id)
            session_state_manager.set_streaming_state(session_id, True)

            # Create session dependencies
            session_deps = ChatSessionDeps(session_id=session_id)
            logger.info("✅ Session dependencies created")

            # Get chat history for context
            chat_history = await session_state_manager.get_chat_history(session_id)
            logger.info(f"✅ Retrieved {len(chat_history)} messages from chat history")

            # Convert chat history to Pydantic AI format
            pydantic_messages = self._convert_db_messages_to_pydantic_ai(chat_history)
            logger.info(f"✅ Converted {len(pydantic_messages)} messages to Pydantic AI format")

            # Save user message to database
            try:
                await session_state_manager.save_message(
                    session_id=session_id,
                    role="user",
                    content=message,
                    metadata={"user_email": user_email}
                )
                logger.info("✅ User message saved to database")
            except Exception as db_error:
                logger.error(f"❌ Failed to save user message: {db_error}")

            # Start streaming response
            logger.info("🌊 Starting agent stream...")
            full_response = ""
            chunk_count = 0

            try:
                # Run agent with message history and delta streaming
                async for chunk in agent.run_stream(
                    message,
                    message_history=pydantic_messages,
                    deps=session_deps,
                    stream_delta=True  # Enable delta streaming for incremental text
                ):
                    chunk_count += 1

                    # Get the delta text from the chunk (delta=True ensures incremental text)
                    if hasattr(chunk, 'delta'):
                        delta_text = chunk.delta
                    elif hasattr(chunk, 'text'):
                        delta_text = chunk.text
                    else:
                        # Try to extract text from chunk
                        delta_text = str(chunk)
                    
                    if delta_text:
                        full_response += delta_text
                        
                        # Format the response chunk for frontend
                        response_data = {
                            "type": "chunk",
                            "content": delta_text,
                            "session_id": session_id,
                            "chunk_index": chunk_count
                        }
                        
                        # Convert to JSON and format for SSE
                        json_response = json.dumps(response_data, ensure_ascii=False)
                        yield f"data: {json_response}\n\n"
                        
                        logger.debug(f"📦 Sent chunk {chunk_count}: {delta_text[:50]}...")

            except Exception as stream_error:
                logger.error(f"❌ Error during agent streaming: {stream_error}")
                error_response = {
                    "type": "error",
                    "content": f"I apologize, but I encountered an error while processing your request: {str(stream_error)}",
                    "session_id": session_id
                }
                json_response = json.dumps(error_response, ensure_ascii=False)
                yield f"data: {json_response}\n\n"
                return

            # Save complete assistant response to database
            if full_response.strip():
                try:
                    await session_state_manager.save_message(
                        session_id=session_id,
                        role="assistant",
                        content=full_response,
                        metadata={
                            "user_email": user_email,
                            "chunk_count": chunk_count,
                            "response_length": len(full_response)
                        }
                    )
                    logger.info(f"✅ Assistant response saved to database ({len(full_response)} chars)")
                except Exception as db_error:
                    logger.error(f"❌ Failed to save assistant response: {db_error}")

            # Send completion signal
            completion_data = {
                "type": "complete",
                "content": full_response,
                "session_id": session_id,
                "total_chunks": chunk_count
            }
            json_response = json.dumps(completion_data, ensure_ascii=False)
            yield f"data: {json_response}\n\n"

            logger.info(f"✅ Streaming completed for session: {session_id}")
            logger.info(f"📊 Total chunks sent: {chunk_count}")
            logger.info(f"📝 Total response length: {len(full_response)} characters")

        except Exception as e:
            logger.error(f"❌ Critical error in stream_agent_response: {e}", exc_info=True)
            
            # Send error response
            error_data = {
                "type": "error",
                "content": f"I apologize, but a critical error occurred: {str(e)}",
                "session_id": session_id
            }
            json_response = json.dumps(error_data, ensure_ascii=False)
            yield f"data: {json_response}\n\n"

        finally:
            # Always reset streaming state
            session_state_manager.set_streaming_state(session_id, False)
            logger.info(f"🔄 Streaming state reset for session: {session_id}")

# Global streaming service instance
streaming_service = StreamingService()
