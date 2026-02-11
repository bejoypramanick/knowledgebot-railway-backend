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
from .agent_manager import agent_manager

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
            tool_call_count = 0

            try:
                # Run agent with message history and stream text deltas
                # Force tool calling: search_knowledge_base ALWAYS, others optional
                from google.genai import types

                async with agent.run_stream(
                    message,
                    message_history=pydantic_messages,
                    deps=session_deps,
                    model_settings={
                        'tool_choice': types.ToolChoice(
                            function_calling=types.FunctionCallingConfig(
                                mode=types.FunctionCallingMode.ANY
                            )
                        ),
                        'cache_system_prompt': True  # Enable prompt caching for performance
                    }
                ) as result:
                    logger.info("🔧 Agent streaming with FORCED TOOL CALLING (FunctionCallingMode.ANY)")
                    # Stream text with delta=True for incremental chunks
                    async for delta_text in result.stream_text(delta=True):
                        chunk_count += 1
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

                    # After streaming, check for tool invocations in the conversation
                    logger.info("🔍 Checking for tool invocations...")
                    
            
                    
                    try:
                        # Access all messages to see tool calls
                        all_messages = result.all_messages()
                        for msg in all_messages:
                            # Check if message contains tool calls
                            if hasattr(msg, 'parts'):
                                for part in msg.parts:
                                    if hasattr(part, 'tool_name'):
                                        tool_call_count += 1
                                        tool_name = getattr(part, 'tool_name', 'unknown')
                                        tool_args = getattr(part, 'args', {})
                                        logger.info(f"🔧 Tool Call #{tool_call_count}: {tool_name}")
                                        logger.info(f"   Args: {tool_args}")
                                    elif hasattr(part, 'content') and 'tool_name' in str(type(part)):
                                        tool_call_count += 1
                                        logger.info(f"🔧 Tool Call #{tool_call_count}: {type(part).__name__}")

                        if tool_call_count > 0:
                            logger.info(f"✅ Total tool calls made: {tool_call_count}")
                            # Force fresh agent creation next time to ensure tools work properly
                            agent_manager.clear_agent_cache(session_id)
                            logger.info(f"🔄 Cleared agent cache for session {session_id} to ensure fresh tool state")
                        else:
                            logger.info("ℹ️ No tool calls were made in this response")
                    except Exception as tool_check_error:
                        logger.warning(f"⚠️ Could not check tool calls: {tool_check_error}")

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
                # Log the full response to see formatting and citations
                logger.info("=" * 80)
                logger.info("📝 FULL AGENT RESPONSE (final output to user):")
                logger.info(full_response)
                logger.info("=" * 80)

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

            # Send completion signal (without content to avoid duplication)
            completion_data = {
                "type": "complete",
                "session_id": session_id,
                "total_chunks": chunk_count,
                "total_length": len(full_response)
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
