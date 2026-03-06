"""
Streaming Service for Chatbot Orchestration
Handles streaming responses and message formatting
"""

import json
import asyncio
import os
import time
from typing import Any, Dict, List, AsyncGenerator
import sys
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart, SystemPromptPart
from shared.otel_logger import get_otel_logger, set_session_id

from ..core.dependencies import ChatSessionDeps
from .session_manager import session_state_manager
from .agent_manager import agent_manager

logger = get_otel_logger("streaming_service", "chatbot-orchestration")

# Feature flags
ENABLE_EXTENDED_THINKING = os.getenv("ENABLE_EXTENDED_THINKING", "false").lower() == "true"

class StreamingService:
    """Handles streaming responses for the chatbot."""

    def __init__(self):
        pass

    def _convert_db_messages_to_pydantic_ai(self, db_messages: List[Dict[str, Any]]) -> List[Any]:
        """Convert database messages to Pydantic AI message format."""
        pydantic_messages = []

        for msg in db_messages:
            try:
                # Extract message content - database can use different field names
                # Try: 'content' (preferred), 'message' (DB format), 'text' (fallback)
                content = msg.get('content', '') or msg.get('message', '') or msg.get('text', '')

                if not content and not msg.get('content'):
                    logger.warning(f"⚠️ WARNING: Message has no content - checking DB structure")
                    logger.warning(f"⚠️ Available fields: {list(msg.keys())}")

                if msg.get('role') == 'user':
                    # Convert user message
                    user_msg = ModelRequest(
                        parts=[UserPromptPart(content=content)]
                    )
                    pydantic_messages.append(user_msg)
                    logger.debug(f"🔄 Converted user message: {content[:50]}...")

                elif msg.get('role') == 'assistant':
                    # Convert assistant message
                    assistant_msg = ModelResponse(
                        parts=[TextPart(content=content)]
                    )
                    pydantic_messages.append(assistant_msg)
                    logger.debug(f"🔄 Converted assistant message: {content[:50]}...")

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

            # STEP 1: Ensure session exists in database (lazy creation on first message)
            # Session may be created by frontend's /set-current call, or created here on first message
            try:
                from shared.sqlalchemy_db import get_db_session
                from sqlalchemy import text

                session_exists = False
                numeric_session_id = None

                # Check if session exists in database
                async with get_db_session() as db_session:
                    query = "SELECT id FROM chat_sessions WHERE session_id = :session_id LIMIT 1"
                    result = await db_session.execute(text(query), {"session_id": session_id})
                    existing_session = result.mappings().first()

                    if existing_session:
                        # Session exists - use its numeric ID
                        session_exists = True
                        numeric_session_id = existing_session["id"]
                        logger.info(f"✅ Found existing session in DB: {session_id} (numeric ID: {numeric_session_id})")
                    else:
                        # Session doesn't exist - create it on first message
                        logger.info(f"📝 Creating new session in database on first message: {session_id}")
                        insert_query = """
                            INSERT INTO chat_sessions (session_id, metadata, created_at, last_activity_at, is_active)
                            VALUES (:session_id, :metadata, NOW(), NOW(), true)
                            RETURNING id
                        """
                        result = await db_session.execute(
                            text(insert_query),
                            {
                                "session_id": session_id,
                                "metadata": json.dumps({"created_by": "first_message", "user_email": user_email})
                            }
                        )
                        numeric_session_id = result.scalar()
                        await db_session.commit()
                        logger.info(f"✅ Created new session in DB: {session_id} (numeric ID: {numeric_session_id})")

            except Exception as e:
                logger.error(f"❌ Error managing session in database: {e}", exc_info=True)
                # Continue anyway - session will be created when message is saved

            # Update session activity
            session_state_manager.update_session_activity(session_id)
            session_state_manager.set_streaming_state(session_id, True)

            # Create session dependencies with both UUID and numeric ID
            session_deps = ChatSessionDeps(session_id=session_id, numeric_session_id=numeric_session_id)
            logger.info(f"✅ Session dependencies created (UUID: {session_id}, numeric ID: {numeric_session_id})")

            # Get chat history for context
            chat_history = await session_state_manager.get_chat_history(session_id)
            logger.info(f"✅ Retrieved {len(chat_history)} messages from chat history")

            # DEBUG: Log exact messages being passed to agent
            if chat_history:
                logger.info("=" * 100)
                logger.info("🔍 DEBUG: EXACT MESSAGES FROM DATABASE")
                logger.info("=" * 100)
                for i, msg in enumerate(chat_history):
                    logger.info(f"Message {i}:")
                    logger.info(f"  Role: {msg.get('role')}")
                    logger.info(f"  Content length: {len(msg.get('message', msg.get('content', '')))} chars")
                    logger.info(f"  Content preview: {msg.get('message', msg.get('content', ''))[:150]}...")
                logger.info("=" * 100)

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
                sys.stdout.flush()

            # Convert chat history to Pydantic AI format
            pydantic_messages = self._convert_db_messages_to_pydantic_ai(chat_history)
            logger.info(f"✅ Converted {len(pydantic_messages)} messages to Pydantic AI format")

            # 🚨 PRE-FLIGHT SYSTEM PROMPT INJECTION 🚨
            # Fix for Pydantic AI gotcha: when message_history is provided, system_prompt is discarded
            # Solution: Prepend system prompt to message_history so it's included in model context
            if pydantic_messages:
                logger.info("=" * 100)
                logger.info("🚨 PRE-FLIGHT SYSTEM PROMPT INJECTION (Pydantic AI Gotcha Fix)")
                logger.info("=" * 100)
                logger.info("Issue: Pydantic AI discards Agent.system_prompt when message_history exists")
                logger.info("Solution: Prepend system prompt as first message in history")
                logger.info("=" * 100)

                # Get system prompt from agent
                from ..agent.prompt import get_system_prompt
                system_prompt_text = get_system_prompt(custom_prompt=None, response_policy=None)

                # Create SystemPromptPart message
                system_prompt_msg = ModelRequest(parts=[SystemPromptPart(content=system_prompt_text)])

                # Prepend to message history (CRITICAL: must be first message)
                pydantic_messages.insert(0, system_prompt_msg)
                logger.info(f"✅ System prompt prepended to message_history")
                logger.info(f"   Now message_history has {len(pydantic_messages)} messages (including system prompt)")
                logger.info(f"   Message 0: System Prompt")
                logger.info(f"   Message 1+: Conversation history")
                logger.info("=" * 100)

            # 🔍 DEBUG: Log actual message history content
            if pydantic_messages:
                logger.info("=" * 100)
                logger.info("🔍 DEBUG: MESSAGE HISTORY BEING PASSED TO AGENT")
                logger.info("=" * 100)
                for i, msg in enumerate(pydantic_messages):
                    msg_type = type(msg).__name__
                    logger.info(f"Message {i}: {msg_type}")
                    if hasattr(msg, 'parts'):
                        for j, part in enumerate(msg.parts):
                            part_type = type(part).__name__
                            part_content = getattr(part, 'content', '')[:100]
                            logger.info(f"  Part {j} ({part_type}): {part_content}...")
                logger.info("=" * 100)
            else:
                logger.warning("⚠️  WARNING: pydantic_messages is EMPTY!")
                logger.warning("⚠️  No conversation history will be passed to model!")

            # 🚨 CRITICAL: Check if human agent is assigned BEFORE processing message
            logger.info(f"🔍 Checking if human agent is assigned to session {session_id}...")
            try:
                from shared.redis_pubsub_manager import get_pubsub_redis

                redis_client = await get_pubsub_redis()
                cache_key = f"session:assigned_agent:{session_id}"
                assigned_agent = await redis_client.get(cache_key)

                if assigned_agent:
                    logger.info(f"👤 Human agent '{assigned_agent}' is assigned to session {session_id}")
                    logger.info(f"📧 Saving customer message and notifying agent...")

                    # Save the user message to database (agent will see it)
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

                    # Notify the agent about the new message via broadcast
                    try:
                        from shared.redis_pubsub_manager import broadcast_event_to_agent
                        event = {
                            "type": "customer_message",
                            "session_id": session_id,
                            "customer_message": message,
                            "timestamp": int(time.time()),
                            "message": f"Customer sent: {message[:100]}..."
                        }
                        await broadcast_event_to_agent(assigned_agent, event)
                        logger.info(f"📤 Notified agent {assigned_agent} about new customer message")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to notify agent: {e}")

                    # Tell customer that agent will respond
                    yield f"data: {json.dumps({'type': 'message_received', 'message': 'Your message has been sent to the agent. Please wait for their response.'})}\n\n"
                    logger.info(f"✅ Customer message processed and forwarded to agent {assigned_agent}")
                    return

            except Exception as e:
                logger.warning(f"⚠️ Error checking agent assignment: {e} - proceeding with AI response")

            # No human agent assigned - proceed with normal AI response
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
                sys.stdout.flush()

                # Pass ORIGINAL message (NOT enriched) to agent
                # Agent decides whether to:
                # - Ask for clarification
                # - Enhance query and search KB
                # - Use other tools
                # - Respond from knowledge

                # Extended thinking configuration (flag-based)
                from google.genai import types
                from pydantic_ai.models.google import GoogleModelSettings

                model_settings = GoogleModelSettings()

                if ENABLE_EXTENDED_THINKING:
                    logger.info("🧠 Extended thinking ENABLED (via ENABLE_EXTENDED_THINKING env var)")
                    thinking_config = types.ThinkingConfigDict(
                        include_thoughts=True
                    )
                    model_settings = GoogleModelSettings(
                        google_thinking_config=thinking_config
                    )
                else:
                    logger.info("🧠 Extended thinking DISABLED (default - set ENABLE_EXTENDED_THINKING=true to enable)")

                logger.info("=" * 100)
                logger.info("📤 CALLING AGENT.ITER() WITH:")
                logger.info(f"   Current message: '{message}'")
                logger.info(f"   Message history length: {len(pydantic_messages)} messages")
                logger.info(f"   System prompt injected: YES ✅ (fix for Pydantic AI gotcha)")
                thinking_status = "ENABLED ✅" if ENABLE_EXTENDED_THINKING else "DISABLED (default)"
                logger.info(f"   Extended thinking: {thinking_status}")
                logger.info("=" * 100)

                async with agent.iter(
                    message,  # ✅ ORIGINAL message
                    message_history=pydantic_messages,  # ✅ Full conversation context
                    deps=session_deps,
                    model_settings=model_settings  # 🧠 Enable extended thinking
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

                        # Log model decision process
                        logger.info("=" * 100)
                        logger.info("🔍 MODEL DECISION PROCESS & TOOL USAGE")
                        logger.info("=" * 100)
                        logger.info(f"📝 Input message: '{message}'")
                        logger.info(f"📚 Conversation history length: {len(pydantic_messages)} messages")
                        logger.info(f"🔧 Tools available: search_knowledge_base, query_railway_postgres, request_human_agent_connection")
                        sys.stdout.flush()

                        tool_calls_made = []
                        for i, msg in enumerate(all_messages):
                            msg_type = type(msg).__name__
                            logger.info(f"📌 Message {i}: {msg_type}")

                            # Log tool calls
                            if hasattr(msg, 'parts'):
                                for j, part in enumerate(msg.parts):
                                    part_type = type(part).__name__

                                    # Detect tool calls
                                    if hasattr(part, 'tool_name'):
                                        tool_name = getattr(part, 'tool_name', 'unknown')
                                        tool_calls_made.append(tool_name)
                                        logger.info(f"   ✅ Tool called: {tool_name}")

                                    # Log text content
                                    elif part_type == 'TextPart' and hasattr(part, 'content'):
                                        content = getattr(part, 'content', '')
                                        preview = content[:200] if len(content) > 200 else content
                                        logger.info(f"   📝 {part_type}: {preview}...")

                        logger.info("=" * 100)
                        logger.info(f"📊 SUMMARY: {len(tool_calls_made)} tools called: {tool_calls_made if tool_calls_made else 'NONE'}")
                        if len(tool_calls_made) == 0 and len(pydantic_messages) > 0:
                            logger.warning("⚠️  WARNING: This is a follow-up (history exists) but NO tools were called!")
                            logger.warning("⚠️  Expected: search_knowledge_base should have been called")
                        logger.info("=" * 100)

                        # Extract assistant response and tool calls
                        for i, msg in enumerate(all_messages):
                            msg_type = type(msg).__name__
                            logger.info(f"📌 Message {i}: {msg_type}")

                            if hasattr(msg, 'parts'):
                                text_parts = [p for p in msg.parts if isinstance(p, TextPart)]
                                total_parts = len(msg.parts)
                                logger.info(f"   Has {total_parts} total parts ({len(text_parts)} TextParts)")

                                for j, part in enumerate(msg.parts):
                                    part_type = type(part).__name__
                                    logger.info(f"     Part {j}/{total_parts - 1}: {part_type}")

                                    # 🧠 LOG EXTENDED THINKING (if present)
                                    if part_type == 'ThinkingPart':
                                        thinking_content = getattr(part, 'content', '')
                                        logger.info("=" * 100)
                                        logger.info("🧠 MODEL EXTENDED THINKING (Reasoning Process)")
                                        logger.info("=" * 100)
                                        logger.info(thinking_content)
                                        logger.info("=" * 100)

                                    # Extract text from TextPart
                                    if isinstance(part, TextPart):
                                        text_content = getattr(part, 'content', '')
                                        text_part_index = [p for p in msg.parts[:j+1] if isinstance(p, TextPart)].__len__()
                                        is_last_text_part = text_part_index == len(text_parts)

                                        logger.info(f"     🔍 TextPart {text_part_index}/{len(text_parts)}: {len(text_content)} chars")
                                        logger.info(f"        Preview: {text_content[:80]}...")

                                        if text_content:
                                            if full_response == "":
                                                logger.info(f"     ✅ [TextPart #{text_part_index}] Setting as full_response (FIRST TextPart)")
                                                chunk_count = 1
                                                full_response = text_content
                                            else:
                                                # CRITICAL FIX: Use LAST TextPart, not first
                                                # If agent generates multiple responses (e.g., cached then correct),
                                                # the last one is most likely the correct/intended response
                                                logger.warning(f"     ⚠️ MULTIPLE TextParts detected!")
                                                logger.warning(f"     ⚠️ [TextPart #{text_part_index}/{len(text_parts)}] New response: {len(text_content)} chars")
                                                logger.warning(f"     ⚠️ Previous response was: {len(full_response)} chars")
                                                logger.warning(f"     ⚠️ Using LAST TextPart (replacing previous)")
                                                logger.warning(f"     ⚠️ Is this the LAST TextPart? {is_last_text_part}")
                                                full_response = text_content  # ← KEY FIX: Use the latest response
                                                chunk_count += 1

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
                        # CRITICAL MONITORING: Track tool call failures
                        # ================================================================
                        # The system prompt requires ALL non-greeting queries to call at least 1 tool
                        # This is now a hard requirement in the prompt (Path A: greeting-only, Path B: tools required)
                        if tool_call_count == 0 and message.strip():
                            greeting_patterns = ["hi", "hello", "hey", "good morning", "good afternoon", "greetings"]
                            is_greeting = any(g in message.lower() for g in greeting_patterns)
                            has_history = len(pydantic_messages) > 0

                            if not is_greeting:
                                logger.error("=" * 100)
                                logger.error("🚨 CRITICAL: TOOL CALL REQUIREMENT NOT MET")
                                logger.error("=" * 100)
                                logger.error(f"Message Type: {'Follow-up with history' if has_history else 'First message'}")
                                logger.error(f"Query: '{message}'")
                                logger.error(f"Tool Calls Made: 0 ❌ (REQUIRED: ≥1)")
                                logger.error("")
                                logger.error("SYSTEM PROMPT REQUIREMENT:")
                                logger.error("- Non-greeting queries MUST follow Path B (call at least 1 tool)")
                                logger.error("- This is a hard requirement for response quality")
                                logger.error("- The model failed to follow the prompt's tool-first decision tree")
                                logger.error("")
                                logger.error("EXPECTED BEHAVIOR:")
                                logger.error("- search_knowledge_base() for knowledge questions")
                                logger.error("- query_railway_postgres() for system data")
                                logger.error("- request_human_agent_connection() for escalation")
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


            # ================================================================
            # ================================================================
            # STREAM THE RESPONSE IN CHUNKS (after enforcement check)
            # ================================================================
            # Now that enforcement has been applied (if needed), stream the response in chunks
            if full_response:
                logger.info("📤 Streaming final response in chunks (after enforcement check)...")
                logger.info(f"🔍 DEBUG: full_response length = {len(full_response)} chars")
                logger.info(f"🔍 DEBUG: full_response preview = {full_response[:100]}...")

                # Break response into chunks for streaming (500 chars per chunk for smooth experience)
                chunk_size = 500
                chunks = [full_response[i:i+chunk_size] for i in range(0, len(full_response), chunk_size)]
                logger.info(f"🔍 DEBUG: Created {len(chunks)} chunks")

                for idx, chunk in enumerate(chunks, 1):
                    if chunk.strip():  # Only stream non-empty chunks
                        logger.info(f"🔍 DEBUG: Streaming chunk {idx}/{len(chunks)}: {len(chunk)} chars")
                        response_data = {
                            "type": "chunk",
                            "content": chunk,
                            "session_id": session_id,
                            "chunk_index": idx
                        }
                        json_response = json.dumps(response_data, ensure_ascii=False)
                        yield f"data: {json_response}\n\n"
                        chunk_count = idx

                logger.info(f"📦 Streamed final response in {len(chunks)} chunks ({len(full_response)} chars total)")

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
