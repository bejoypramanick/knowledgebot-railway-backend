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

            # HYBRID APPROACH: Manually call search_knowledge_base to ensure it happens,
            # but allow other tools to be called if needed. Prevent duplicate calls.
            try:
                from ..tools.knowledge_tools import search_knowledge_base
                logger.info("🔍 Manually calling search_knowledge_base to ensure KB search happens...")
                kb_results = await search_knowledge_base(message)
                logger.info(f"✅ KB Search completed: {len(kb_results)} chars returned")

                # Inject KB results into message AND tell agent NOT to call KB again
                # This prevents redundant calls while still allowing other tools if needed
                enriched_message = f"""USER QUERY: {message}

KNOWLEDGE BASE ALREADY SEARCHED: The knowledge base search was already performed for you.

RAW KNOWLEDGE BASE SEARCH RESULTS:
{kb_results}

🔴 CRITICAL FORMATTING INSTRUCTIONS (MANDATORY - NON-NEGOTIABLE):
1. You MUST reformat the knowledge base results above into PROPER HTML
2. You CANNOT output plain text - EVERY response must use HTML tags
3. You MUST wrap paragraphs in <p></p> tags
4. You MUST wrap important terms/names in <strong></strong> tags
5. You MUST wrap emphasized text in <em></em> tags
6. You MUST use <ul><li> for lists or facts
7. You MUST include citations in proper HTML format
8. You MUST NOT use plain text, markdown, or line breaks without HTML tags
9. Format example: <p>Here's <strong>important info</strong> with <em>emphasis</em>.</p>

OTHER INSTRUCTIONS:
- Do NOT call search_knowledge_base again - results already provided above
- If you need additional data, you may call other tools (database, human agent)
- Answer the user's question using the KB results above
- Always include citations with source URLs using <a href="URL" target="_blank">text</a>"""

                logger.info(f"📝 Enriched message with KB results: {len(enriched_message)} chars")
            except Exception as kb_error:
                logger.warning(f"⚠️ Manual KB search failed: {kb_error}")
                # Even if KB search fails, tell agent it was already attempted
                enriched_message = f"""USER QUERY: {message}

KNOWLEDGE BASE ALREADY SEARCHED: Knowledge base search was attempted but failed.

🔴 CRITICAL FORMATTING INSTRUCTIONS (MANDATORY - NON-NEGOTIABLE):
1. You MUST respond in PROPER HTML format
2. You CANNOT output plain text - EVERY response must use HTML tags
3. You MUST wrap paragraphs in <p></p> tags
4. You MUST wrap important information in <strong></strong> tags
5. Format example: <p><strong>Important:</strong> The knowledge base search failed.</p>

INSTRUCTIONS:
1. Inform the user that knowledge base search encountered an error
2. Offer to connect them to a human agent or try alternative queries
3. Use HTML formatting for EVERY part of your response - no plain text"""

            try:
                # Use agent.iter() for proper streaming + tool execution
                logger.info("🔧 Using agent.iter() with pre-searched KB results and duplicate prevention")

                async with agent.iter(
                    enriched_message,
                    message_history=pydantic_messages,
                    deps=session_deps
                ) as run:
                    logger.info("🚀 Starting agent iteration (streaming + tools)")

                    # Import correct message types from pydantic_ai.messages
                    from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

                    # Iterate through agent events/responses (these are Node objects, not ModelResponse)
                    async for event in run:
                        event_type = type(event).__name__
                        logger.info(f"📌 Processing event: {event_type}")
                        # Events are Node types (UserPromptNode, ModelRequestNode, CallToolsNode, End)
                        # We don't stream from these directly - we get response after iteration via run.all_messages()

                    # After iteration completes, get final result
                    logger.info("🔍 Agent iteration completed, extracting response from all_messages()...")
                    try:
                        # Get all messages from the run (this is the correct API for agent.iter())
                        all_messages = run.all_messages()
                        logger.info(f"📋 Total messages in conversation: {len(all_messages)}")

                        # Extract assistant response and tool calls
                        for i, msg in enumerate(all_messages):
                            msg_type = type(msg).__name__
                            logger.info(f"📌 Message {i}: {msg_type}")

                            if hasattr(msg, 'parts'):
                                logger.info(f"   Has {len(msg.parts)} parts")
                                for j, part in enumerate(msg.parts):
                                    part_type = type(part).__name__
                                    logger.info(f"     Part {j}: {part_type}")

                                    # Extract text from TextPart
                                    if isinstance(part, TextPart):
                                        text_content = getattr(part, 'content', '')
                                        if text_content and full_response == "":
                                            logger.info(f"     ✅ Found TextPart with {len(text_content)} chars")
                                            chunk_count += 1
                                            full_response = text_content

                                            # Stream the response
                                            response_data = {
                                                "type": "chunk",
                                                "content": text_content,
                                                "session_id": session_id,
                                                "chunk_index": chunk_count
                                            }
                                            json_response = json.dumps(response_data, ensure_ascii=False)
                                            yield f"data: {json_response}\n\n"
                                            logger.info(f"📦 Streamed text from assistant message: {len(text_content)} chars")

                                    # Track tool calls
                                    elif hasattr(part, 'tool_name'):
                                        tool_name = getattr(part, 'tool_name', 'unknown')
                                        tool_args = getattr(part, 'args', {})
                                        tool_call_count += 1
                                        logger.info(f"✅ Tool executed: {tool_name}")
                                        logger.info(f"   Args: {tool_args}")

                        logger.info(f"✅ Agent completed with {tool_call_count} tool calls")
                    except Exception as result_error:
                        logger.error(f"❌ Error extracting results: {result_error}", exc_info=True)
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
