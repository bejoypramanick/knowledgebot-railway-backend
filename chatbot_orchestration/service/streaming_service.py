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
                # Use agent.iter() for proper streaming + tool execution
                # With tool_config to FORCE search_knowledge_base call (prevents tool not being called)
                from pydantic_ai.settings import ModelSettings

                logger.info("🔧 Using agent.iter() with FORCED tool calling (prevents model ignoring tools)")

                # Force at least one tool call to ensure KB is always searched
                forced_settings = ModelSettings(
                    tool_config={
                        'function_calling_config': {
                            'mode': 'ANY',  # Force at least one tool call
                            'allowed_function_names': ['search_knowledge_base']  # Only KB tool
                        }
                    }
                )

                async with agent.iter(
                    message,
                    message_history=pydantic_messages,
                    deps=session_deps,
                    model_settings=forced_settings
                ) as run:
                    logger.info("🚀 Starting agent iteration (streaming + intelligent tools)")

                    # Import correct message types from pydantic_ai.messages
                    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

                    # Iterate through agent events/responses
                    async for event in run:
                        event_type = type(event).__name__
                        logger.info(f"📌 Processing event: {event_type}")

                        # Check if event is a ModelResponse (contains text/tools)
                        if isinstance(event, ModelResponse):
                            logger.info(f"📝 ModelResponse with {len(event.parts)} parts")

                            # Iterate through parts in the response
                            for i, part in enumerate(event.parts):
                                part_type = type(part).__name__
                                logger.info(f"  Part {i}: {part_type}")

                                # Stream text parts to frontend
                                if isinstance(part, TextPart):
                                    text_content = part.content
                                    logger.info(f"    TextPart content length: {len(text_content) if text_content else 0}")
                                    if text_content:
                                        chunk_count += 1
                                        full_response += text_content

                                        # Format the response chunk for frontend
                                        response_data = {
                                            "type": "chunk",
                                            "content": text_content,
                                            "session_id": session_id,
                                            "chunk_index": chunk_count
                                        }

                                        # Convert to JSON and format for SSE
                                        json_response = json.dumps(response_data, ensure_ascii=False)
                                        yield f"data: {json_response}\n\n"

                                        logger.info(f"📦 Sent chunk {chunk_count}: {len(text_content)} chars")

                                # Track tool calls
                                elif isinstance(part, ToolCallPart):
                                    tool_call_count += 1
                                    tool_name = getattr(part, 'tool_name', 'unknown')
                                    logger.info(f"    🔧 Tool call: {tool_name}")
                                else:
                                    logger.info(f"    Other part type: {part_type}")

                        else:
                            logger.info(f"📌 Other event type: {event_type}")

                    # After iteration completes, get final result
                    logger.info("🔍 Agent iteration completed, checking results...")
                    try:
                        # Get the final output from the run result
                        logger.info(f"🔍 Checking for final_output attribute...")
                        if hasattr(run, 'final_output'):
                            try:
                                final_output = run.final_output()
                                logger.info(f"📦 Final output exists: True")
                                logger.info(f"📦 Final output type: {type(final_output).__name__}")
                                logger.info(f"📦 Final output value: {final_output}")
                                logger.info(f"📦 Final output bool: {bool(final_output)}")
                                logger.info(f"📦 Full response so far: {len(full_response)} chars")

                                # If we didn't stream anything but have final output, stream it now
                                if full_response == "" and final_output:
                                    final_text = str(final_output)
                                    logger.info(f"📦 Converting final_output to string: {len(final_text)} chars")
                                    if final_text and final_text.strip():
                                        chunk_count += 1
                                        full_response = final_text

                                        # Stream final output
                                        response_data = {
                                            "type": "chunk",
                                            "content": final_text,
                                            "session_id": session_id,
                                            "chunk_index": chunk_count
                                        }

                                        json_response = json.dumps(response_data, ensure_ascii=False)
                                        yield f"data: {json_response}\n\n"
                                        logger.info(f"✅ Streamed final output: {len(final_text)} chars")
                                    else:
                                        logger.warning(f"⚠️ Final text is empty after conversion")
                                else:
                                    logger.info(f"⚠️ Skipping final_output: full_response={len(full_response)} chars, final_output={bool(final_output)}")
                            except Exception as final_error:
                                logger.error(f"❌ Error calling final_output(): {final_error}")
                                raise
                        else:
                            logger.warning("⚠️ run object does not have final_output method")

                        # Access all messages to verify tool calls were made
                        all_messages = run.all_messages()
                        for msg in all_messages:
                            if hasattr(msg, 'parts'):
                                for part in msg.parts:
                                    if hasattr(part, 'tool_name'):
                                        tool_name = getattr(part, 'tool_name', 'unknown')
                                        tool_args = getattr(part, 'args', {})
                                        logger.info(f"✅ Tool executed: {tool_name}")
                                        logger.info(f"   Args: {tool_args}")

                        logger.info(f"✅ Agent completed with {tool_call_count} tool calls")
                    except Exception as result_error:
                        logger.warning(f"⚠️ Could not verify results: {result_error}")
                        logger.warning(f"⚠️ Error type: {type(result_error).__name__}")

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
