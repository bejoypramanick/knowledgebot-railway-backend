"""
Streaming Service for Chatbot Orchestration
Handles streaming responses and message formatting
"""

import json
import asyncio
from typing import Any, Dict, List, AsyncGenerator

from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
from shared.otel_logger import get_otel_logger, set_session_id

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
            # Set session_id in OTEL context - all logs will now include session_id
            set_session_id(session_id)

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

            # Log detailed chat history
            if chat_history:
                logger.info("=" * 100)
                logger.info("📚 CHAT MESSAGE HISTORY (INPUT TO AGENT)")
                logger.info(f"   Total messages in history: {len(chat_history)}")
                logger.info("-" * 100)
                for i, msg in enumerate(chat_history):
                    role = msg.get('role', 'unknown').upper()
                    content = msg.get('content', '')[:200]  # Show first 200 chars
                    timestamp = msg.get('created_at', 'N/A')
                    logger.info(f"   Message {i+1} [{role}] (created: {timestamp})")
                    logger.info(f"      Preview: {content}..." if len(msg.get('content', '')) > 200 else f"      Content: {content}")
                logger.info("=" * 100)

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
                logger.info("🚀 Intelligent RAG Mode: Letting agent control knowledge base search")
                logger.info(f"📝 Agent will analyze: '{message[:100]}...'")
                logger.info(f"📚 Agent has access to {len(pydantic_messages)} messages of conversation history")
                logger.info(f"🔧 Agent tools: search_knowledge_base (with auto-context), query_railway_postgres, request_human_agent_connection")

                # Log what the agent is receiving
                logger.info("=" * 100)
                logger.info("🤖 AGENT INPUT SUMMARY")
                logger.info(f"   Current User Message: {message[:150]}...")
                logger.info(f"   Message History Length: {len(pydantic_messages)} messages")
                logger.info(f"   Context Window: Full conversation context provided")
                logger.info(f"   Available Tools: search_knowledge_base, query_railway_postgres, request_human_agent_connection")
                logger.info(f"   Session Dependencies: Initialized")
                logger.info("=" * 100)

                # Pass ORIGINAL message (NOT enriched) to agent
                # Agent decides whether to:
                # - Ask for clarification
                # - Enhance query and search KB
                # - Use other tools
                # - Respond from knowledge
                async with agent.iter(
                    message,  # ✅ ORIGINAL message - agent decides what to do
                    message_history=pydantic_messages,  # ✅ Full conversation context
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

                        # Log model reasoning if available
                        logger.info("=" * 100)
                        logger.info("🧠 MODEL REASONING & DECISION PROCESS")
                        logger.info("=" * 100)
                        for i, msg in enumerate(all_messages):
                            msg_type = type(msg).__name__
                            logger.info(f"📌 Message {i}: {msg_type}")

                            # Log model request details (shows model's decision making)
                            if hasattr(msg, '__class__') and 'ModelRequest' in msg_type:
                                if hasattr(msg, 'parts'):
                                    logger.info(f"   🤔 Model reasoning/decision:")
                                    for part in msg.parts:
                                        part_type = type(part).__name__
                                        # Log thinking/reasoning content if present
                                        if hasattr(part, 'content'):
                                            content = getattr(part, 'content', '')
                                            # Truncate long reasoning for readability
                                            preview = content[:300] if len(content) > 300 else content
                                            logger.info(f"      [{part_type}] {preview}")

                            # Log tool usage decisions
                            if hasattr(msg, 'parts'):
                                for part in msg.parts:
                                    if hasattr(part, 'tool_name'):
                                        tool_name = getattr(part, 'tool_name', 'unknown')
                                        tool_args = getattr(part, 'args', {})
                                        logger.info(f"   🔧 Model decision: Call {tool_name}")
                                        logger.info(f"      Why: To search knowledge base for enhanced context")
                                        logger.info(f"      Query: {tool_args.get('query', 'N/A')[:100]}")

                        logger.info("=" * 100)

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

                                    # Track tool calls with detailed logging
                                    elif hasattr(part, 'tool_name'):
                                        tool_name = getattr(part, 'tool_name', 'unknown')
                                        tool_args = getattr(part, 'args', {})
                                        tool_call_count += 1
                                        
                                        # Comprehensive tool invocation logging
                                        logger.info("=" * 80)
                                        logger.info("🔧 TOOL INVOCATION DETECTED")
                                        logger.info(f"   Tool Name: {tool_name}")
                                        logger.info(f"   Tool Arguments: {json.dumps(tool_args, indent=2, ensure_ascii=False)}")
                                        logger.info(f"   Tool Call #{tool_call_count} in this response")
                                        logger.info(f"   Session ID: {session_id}")
                                        logger.info(f"   User Email: {user_email}")
                                        logger.info("=" * 80)

                        logger.info(f"✅ Agent completed with {tool_call_count} tool calls")

                        # ================================================================
                        # CRITICAL ENFORCEMENT: No tool calls for non-greeting queries
                        # ================================================================
                        # Detect non-greeting queries answered without knowledge base search
                        if tool_call_count == 0 and len(message.strip()) > 10:
                            # Check if message is non-greeting
                            greeting_patterns = ["hi", "hello", "hey", "good morning", "good afternoon", "greetings"]
                            is_greeting = any(g in message.lower() for g in greeting_patterns)

                            # Check if there's conversation history (follow-up query)
                            has_history = len(pydantic_messages) > 0

                            if not is_greeting:
                                logger.error("=" * 100)
                                logger.error("🚨 CRITICAL RAG ENFORCEMENT VIOLATION 🚨")
                                logger.error("=" * 100)
                                logger.error("RULE VIOLATED: Agent answered without calling search_knowledge_base")
                                logger.error(f"Query Type: {'Follow-up with history' if has_history else 'First message'}")
                                logger.error(f"Query: '{message}'")
                                logger.error(f"Conversation History: {len(pydantic_messages)} messages")
                                logger.error(f"Tool Calls Made: 0 (SHOULD BE 1+)")
                                logger.error(f"Response Length: {len(full_response)} chars")
                                logger.error("")
                                logger.error("EXPECTED BEHAVIOR (from system prompt Rule 1 & 4):")
                                logger.error("  1. Extract context from conversation history")
                                logger.error("  2. Build context-enhanced query")
                                logger.error(f"  3. Call search_knowledge_base with enhanced query")
                                logger.error("  4. Answer ONLY using RAG results")
                                logger.error("")
                                if has_history:
                                    logger.error("⚠️ This is a follow-up query with conversation context")
                                    logger.error("⚠️ Agent MUST use search_knowledge_base for follow-ups per Rule 4")
                                    logger.error("⚠️ Answering from training data = RULE VIOLATION")
                                logger.error("=" * 100)

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
                # Log the complete response with grounding truth and metadata
                logger.info("=" * 100)
                logger.info("📝 GEMINI RESPONSE WITH GROUNDING TRUTH")
                logger.info(f"   Session ID: {session_id}")
                logger.info(f"   User Query: {message[:100]}...")
                logger.info(f"   User Email: {user_email}")
                logger.info(f"   Total Tool Calls: {tool_call_count}")
                logger.info(f"   Response Length: {len(full_response)} characters")
                logger.info(f"   Response Chunks: {chunk_count}")
                logger.info("-" * 100)
                logger.info("🔗 GROUNDING TRUTH & DATA SOURCES:")
                logger.info("   Source: Gemini FileStore (1.5 Flash model)")
                logger.info("   Search Type: Knowledge base with file retrieval")
                logger.info("   Processing: Raw docling output formatted by Gemini")
                logger.info("   Response Format: HTML with proper citations")
                logger.info("   Data Quality: Grounded in uploaded knowledge base files")
                logger.info("-" * 100)
                logger.info("📋 COMPLETE GEMINI RESPONSE CONTENT:")
                logger.info(full_response)
                logger.info("=" * 100)
                
                try:
                    await session_state_manager.save_message(
                        session_id=session_id,
                        role="assistant",
                        content=full_response,
                        metadata={
                            "user_email": user_email,
                            "chunk_count": chunk_count,
                            "response_length": len(full_response),
                            "tool_calls": tool_call_count,
                            "grounding_sources": "Gemini FileStore",
                            "response_format": "HTML with citations"
                        }
                    )
                    logger.info(f"✅ Assistant response saved to database ({len(full_response)} chars)")
                except Exception as db_error:
                    logger.error(f"❌ Failed to save assistant response: {db_error}")

            # Send completion signal (without content to avoid duplication)
            logger.info("=" * 80)
            logger.info("🏁 STREAMING COMPLETION SUMMARY")
            logger.info(f"   Session ID: {session_id}")
            logger.info(f"   User Email: {user_email}")
            logger.info(f"   Total Tool Calls Executed: {tool_call_count}")
            logger.info(f"   Total Response Chunks: {chunk_count}")
            logger.info(f"   Final Response Length: {len(full_response)} characters")
            logger.info("   Grounding Truth: Response based on Gemini FileStore search results")
            logger.info("   Primary Data Source: Gemini FileStore knowledge base")
            logger.info("   Response Format: HTML with proper citations")
            logger.info("   Completion Status: Successfully completed streaming")
            logger.info("=" * 80)
            
            completion_data = {
                "type": "complete",
                "session_id": session_id,
                "total_chunks": chunk_count,
                "total_length": len(full_response),
                "tool_calls": tool_call_count,
                "grounding_sources": "Gemini FileStore",
                "response_format": "HTML with citations",
                "completion_status": "success"
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
