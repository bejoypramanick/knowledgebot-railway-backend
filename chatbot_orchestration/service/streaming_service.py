"""
Streaming Service for Chatbot Orchestration
Handles streaming responses and message formatting
"""

import json
import asyncio
import os
import re
import time
from typing import Any, Dict, List, AsyncGenerator
import sys
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart, SystemPromptPart
from shared.otel_logger import get_otel_logger, set_session_id

from ..core.dependencies import ChatSessionDeps
from ..core.ai import MODEL_NAME
from .session_manager import session_state_manager
from .agent_manager import agent_manager

logger = get_otel_logger("streaming_service", "chatbot-orchestration")

# Feature flags
ENABLE_EXTENDED_THINKING = os.getenv("ENABLE_EXTENDED_THINKING", "false").lower() == "true"

class StreamingService:
    """Handles streaming responses for the chatbot."""

    def __init__(self):
        from ..dao.chat_dao import ChatDAO
        self.chat_dao = ChatDAO()

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
    
    def _detect_agent_request(self, message: str) -> bool:
        """
        Detect if user is explicitly requesting a human agent.
        Returns True if message contains agent request keywords.
        """
        message_lower = message.lower().strip()
        
        # Explicit agent request keywords
        agent_keywords = [
            "agent",
            "human",
            "person",
            "representative",
            "support",
            "help me",
            "speak to someone",
            "talk to someone",
            "connect me",
            "real person",
            "customer service",
            "customer support"
        ]
        
        # Check if any keyword is in the message
        for keyword in agent_keywords:
            if keyword in message_lower:
                logger.info(f"🎯 Detected agent request keyword: '{keyword}' in message: '{message[:50]}...'")
                return True
        
        return False

    def _prune_message_history_safe(self, messages: List[Any], max_messages: int = 50) -> List[Any]:
        """
        Safely prune message history while protecting the system prompt at index 0.
        
        IMPORTANT: If message_history has been injected with a system prompt at index 0,
        this method ensures it's NEVER pruned. Only conversation messages (index 1+) are pruned.
        
        Args:
            messages: List of Pydantic AI messages
            max_messages: Maximum number of messages to keep (including system prompt)
        
        Returns:
            Pruned message list with system prompt protected at index 0
        """
        if len(messages) <= max_messages:
            return messages
        
        # Check if first message is a system prompt
        has_system_prompt = (
            len(messages) > 0 and 
            hasattr(messages[0], 'parts') and 
            any(isinstance(part, SystemPromptPart) for part in messages[0].parts)
        )
        
        if has_system_prompt:
            # Keep system prompt at index 0, prune from the middle of conversation history
            # This preserves recent context while protecting the system prompt
            system_prompt = messages[0]
            conversation = messages[1:]
            
            # Keep only the most recent messages
            pruned_conversation = conversation[-(max_messages - 1):]
            
            logger.info(f"🔄 Pruned message history (protected system prompt at index 0)")
            logger.info(f"   Original: {len(messages)} messages")
            logger.info(f"   Pruned: {len(pruned_conversation) + 1} messages")
            logger.info(f"   System prompt: PROTECTED at index 0")
            
            return [system_prompt] + pruned_conversation
        else:
            # No system prompt, prune normally from the end
            pruned = messages[-max_messages:]
            logger.info(f"🔄 Pruned message history (no system prompt)")
            logger.info(f"   Original: {len(messages)} messages")
            logger.info(f"   Pruned: {len(pruned)} messages")
            return pruned

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

            # STEP 1: Ensure session exists in Redis (DB 6) — zero PG connections
            # PG row created lazily by write-through or ensure_numeric_id() on first message
            try:
                from shared.redis_chat_store import get_chat_store

                chat_store = get_chat_store()
                numeric_session_id = None

                # Get or create session in Redis
                redis_session = await chat_store.get_or_create_session(
                    session_uuid=session_id,
                    metadata={"created_by": "first_message", "user_email": user_email}
                )

                if redis_session:
                    numeric_session_id = redis_session.get("db_id")
                    if numeric_session_id:
                        logger.info(f"Found existing session in Redis: {session_id} (numeric ID: {numeric_session_id})")
                    else:
                        # Need PG numeric ID (single PG call, first message only)
                        numeric_session_id = await self.chat_dao.ensure_numeric_id(session_id)
                        logger.info(f"Created PG numeric ID for session: {session_id} -> {numeric_session_id}")
                else:
                    logger.warning(f"Redis session creation returned None for {session_id}")

            except Exception as e:
                logger.error(f"Error managing session in Redis: {e}", exc_info=True)

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

            # System Prompt Strategy: Cache-aware handling
            #
            # If Gemini cache is active:
            #   - System prompt is IN the cache, no need to prepend or rely on Agent.system_prompt
            #   - Always pass message_history (even for first messages)
            #
            # If no cache (fallback - existing two-tier logic):
            #   1. FIRST MESSAGE: Don't provide message_history, use Agent.system_prompt
            #   2. FOLLOW-UP: Prepend SystemPromptPart to message_history

            has_chat_history = len(pydantic_messages) > 0
            cache_name = agent_manager.get_cached_cache_name(session_id)

            logger.info(f"System prompt strategy: cache={'active: ' + cache_name if cache_name else 'none'}, "
                        f"history={len(pydantic_messages)} messages")

            if cache_name:
                # Cache active: system prompt is in the cache
                logger.info("System prompt served from Gemini cache (skipping prepend)")
            elif has_chat_history:
                # FOLLOW-UP MESSAGE (no cache): Must prepend system prompt to message_history
                system_prompt_text = agent_manager.get_cached_system_prompt(session_id)

                if system_prompt_text:
                    system_prompt_msg = ModelRequest(parts=[SystemPromptPart(content=system_prompt_text)])
                    pydantic_messages.insert(0, system_prompt_msg)
                    logger.info(f"System prompt prepended to message_history ({len(system_prompt_text)} chars)")
                else:
                    logger.error(f"System prompt not found in cache for session {session_id}")
                    raise RuntimeError(f"System prompt not found for session {session_id}")
            else:
                # FIRST MESSAGE (no cache): Agent.system_prompt will be used automatically
                logger.info("First message: using Agent.system_prompt (no cache fallback)")

            # 🚨 CRITICAL: Check if user is requesting human agent BEFORE AI responds
            logger.info(f"🔍 Checking if user is requesting human agent...")
            user_wants_agent = self._detect_agent_request(message)
            
            if user_wants_agent:
                logger.info(f"🧑 User explicitly requesting human agent - assigning before AI responds")
                # Assign agent immediately using the tool logic
                try:
                    import httpx
                    config_service_url = os.getenv(
                        'CONFIGURATION_SERVICE_URL',
                        'http://configuration.railway.internal:8080'
                    )
                    endpoint_url = f"{config_service_url}/api/v1/configuration/admin/chat-sessions/request-agent"
                    
                    # Get numeric session ID from Redis/PG
                    numeric_session_id = await self.chat_dao.ensure_numeric_id(session_id)
                    if numeric_session_id:
                            # Call configuration service to assign agent
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                response = await client.post(
                                    endpoint_url,
                                    json={"session_id": numeric_session_id}
                                )
                                
                                if response.status_code == 200:
                                    result = response.json()
                                    assigned_agent = result.get('agent_assigned')
                                    assigned_agent_id = result.get('agent_id')
                                    logger.info(f"✅ Agent {assigned_agent} (ID: {assigned_agent_id}) assigned before AI response")
                                    
                                    # Small delay to ensure database commit completes
                                    await asyncio.sleep(0.1)
                                    
                                    # Verify assignment was saved in database
                                    from shared.sqlalchemy_db import get_db_session as get_db
                                    from sqlalchemy import text as sql_text
                                    async with get_db() as verify_db:
                                        verify_query = """
                                            SELECT u.email as agent_email, u.id as agent_id
                                            FROM session_assignments sa
                                            LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                                            LEFT JOIN users u ON urm.user_id = u.id
                                            WHERE sa.session_id = :session_id AND sa.status = 'active'
                                        """
                                        verify_result = await verify_db.execute(sql_text(verify_query), {"session_id": numeric_session_id})
                                        verify_row = verify_result.mappings().first()
                                        if verify_row:
                                            logger.info(f"Verified agent assignment in database: {verify_row['agent_email']} (ID: {verify_row['agent_id']})")
                                        else:
                                            logger.warning(f"Agent assignment not found in database yet for session {numeric_session_id}")
                                    
                                    # Cache the agent assignment in Redis DB 4
                                    from shared.redis_agent_cache import set_assigned_agent
                                    await set_assigned_agent(session_id, assigned_agent_id)
                                    logger.info(f"Cached agent assignment (DB 4): {session_id} -> {assigned_agent_id}")
                                    
                                    # Save user message first
                                    await session_state_manager.save_message(
                                        session_id=session_id,
                                        role="user",
                                        content=message,
                                        metadata={"user_email": user_email}
                                    )
                                    
                                    # Broadcast session to agent with all messages
                                    from shared.redis_pubsub_manager import broadcast_event_to_agent
                                    from datetime import datetime
                                    
                                    # Get session details and messages from Redis
                                    redis_session = await chat_store.get_session(session_id)
                                    redis_messages = await chat_store.get_messages(session_id)

                                    if redis_session:

                                        messages = []
                                        for i, msg in enumerate(redis_messages):
                                            messages.append({
                                                "id": str(i),
                                                "text": msg.get('content', ''),
                                                "sender": msg.get('role', ''),
                                                "timestamp": msg.get('created_at', datetime.utcnow().isoformat()),
                                                "session_id": session_id
                                            })

                                        # Get customer_name from Redis session metadata
                                        session_metadata = redis_session.get('metadata', {})
                                        customer_name = session_metadata.get('customer_name') if isinstance(session_metadata, dict) else None

                                        if not customer_name:
                                            customer_name = f"User-{numeric_session_id}"

                                        # Build session event
                                        session_event = {
                                            "type": "session_update",
                                            "data": {
                                                "id": str(redis_session.get('db_id', numeric_session_id)),
                                                "session_uuid": session_id,
                                                "customer_name": customer_name,
                                                "customer_email": None,
                                                "status": redis_session.get('archive_status', 'active'),
                                                "last_message_at": redis_session.get('last_activity_at', datetime.utcnow().isoformat()),
                                                "created_at": redis_session.get('started_at'),
                                                "assigned_agent": assigned_agent,
                                                "assigned_agent_id": assigned_agent_id,
                                                "feedback": None,
                                                "customer_feedback": None,
                                                "agent_feedback": None,
                                                "chat_type": "human-handoff",
                                                "is_session_read": False,
                                                "messages": messages
                                            }
                                        }
                                        # Broadcast to assigned agent's specific channel (using user ID)
                                        result = await broadcast_event_to_agent(assigned_agent_id, session_event)
                                        logger.info(f"📤 Broadcasted session_update to agent {assigned_agent} (ID: {assigned_agent_id}) on channel agent:events:{assigned_agent_id}")
                                        logger.info(f"📤 Broadcast result: {result}")
                                        
                                        # ALSO broadcast to all admins via broadcast channel
                                        from shared.redis_pubsub_manager import broadcast_event_to_all_agents
                                        broadcast_result = await broadcast_event_to_all_agents(session_event)
                                        logger.info(f"📢 Broadcasted session_update to ALL admins on channel agent:events:broadcast")
                                        logger.info(f"📢 Broadcast result: {broadcast_result}")
                                        logger.info(f"📤 Session data includes {len(messages)} messages")
                                    
                                    # Send chat_assigned event to customer via SSE
                                    # This will trigger the UI to show the End Session button
                                    chat_assigned_event = {
                                        "type": "chat_assigned",
                                        "session_id": session_id,
                                        "agent_email": assigned_agent,
                                        "agent_id": assigned_agent_id,
                                        "message": "A human agent has been assigned to your chat"
                                    }
                                    
                                    # Broadcast to customer's SSE channel
                                    from shared.redis_pubsub_manager import broadcast_event_to_session
                                    customer_broadcast_result = await broadcast_event_to_session(session_id, chat_assigned_event)
                                    logger.info(f"📤 Sent chat_assigned event to customer on channel customer:events:{session_id}")
                                    logger.info(f"📤 Customer broadcast result: {customer_broadcast_result}")
                                    
                                    # Send confirmation to customer (this will be filtered out by frontend)
                                    confirmation_msg = f"Connected to human agent\n"
                                    
                                    # Save AI confirmation message
                                    await session_state_manager.save_message(
                                        session_id=session_id,
                                        role="assistant",
                                        content=confirmation_msg,
                                        metadata={}
                                    )
                                    
                                    # Stream confirmation to customer with proper SSE format
                                    yield f"data: {json.dumps({'type': 'chunk', 'content': confirmation_msg})}\n\n"
                                    await asyncio.sleep(0.01)  # Small delay to ensure message is sent
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                    logger.info(f"✅ Agent assigned and customer notified via SSE")
                                    return
                                    
                                elif response.status_code == 503:
                                    logger.warning(f"⚠️ No agents available - letting AI respond")
                                    # Fall through to normal AI response
                                else:
                                    logger.error(f"❌ Agent assignment failed: {response.status_code}")
                                    # Fall through to normal AI response
                        
                except Exception as e:
                    logger.error(f"❌ Error assigning agent: {e}")
                    # Fall through to normal AI response
            
            # Check if human agent is already assigned to session
            logger.info(f"Checking if human agent is assigned to session {session_id}...")
            try:
                from shared.redis_agent_cache import get_assigned_agent, set_assigned_agent as cache_set_agent

                assigned_agent_id = await get_assigned_agent(session_id)

                # If not in Redis DB 4 cache, check database
                if not assigned_agent_id:
                    logger.info(f"Agent cache miss (DB 4), checking database...")
                    try:
                        from shared.sqlalchemy_db import get_db_session
                        from sqlalchemy import text

                        async with get_db_session() as db_session:
                            query = """
                                SELECT u.id as agent_id, u.email as agent_email FROM session_assignments sa
                                JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                                JOIN users u ON urm.user_id = u.id
                                WHERE sa.session_id = (SELECT id FROM chat_sessions WHERE session_id = :session_uuid)
                                AND sa.status = 'active'
                                AND u.is_active = true
                                LIMIT 1
                            """
                            result = await db_session.execute(text(query), {"session_uuid": session_id})
                            row = result.mappings().first()
                            if row:
                                assigned_agent_id = row['agent_id']
                                assigned_agent_email = row['agent_email']
                                logger.info(f"Found agent in database: {assigned_agent_email} (ID: {assigned_agent_id})")
                                await cache_set_agent(session_id, assigned_agent_id)
                                logger.info(f"Cached agent assignment (DB 4): {session_id} -> {assigned_agent_id}")
                    except Exception as db_error:
                        logger.warning(f"Database lookup failed: {db_error}")

                if assigned_agent_id:
                    assigned_agent_id = int(assigned_agent_id) if isinstance(assigned_agent_id, (str, bytes)) else assigned_agent_id
                    logger.info(f"👤 Human agent (ID: {assigned_agent_id}) is assigned to session {session_id}")
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
                        await broadcast_event_to_agent(assigned_agent_id, event)
                        logger.info(f"📤 Notified agent (ID: {assigned_agent_id}) about new customer message")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to notify agent: {e}")

                    # Tell customer that agent will respond
                    yield f"data: {json.dumps({'type': 'message_received', 'message': 'Your message has been sent to the agent. Please wait for their response.'})}\n\n"
                    logger.info(f"✅ Customer message processed and forwarded to agent (ID: {assigned_agent_id})")
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
            agent_s3_download_url = None  # Initialize for S3 upload
            
            # Import Redis pubsub manager for posting responses to channels
            from shared.redis_pubsub_manager import broadcast_event_to_session, broadcast_event_to_all_agents, broadcast_event_to_agent
            from shared.redis_agent_cache import get_assigned_agent

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

                from pydantic_ai.models.google import GoogleModelSettings

                # Get response_policy (temperature) from agent manager
                response_policy = 0.5  # Default balanced
                try:
                    persona_config = await agent_manager._fetch_persona_config()
                    response_policy = persona_config.get('response_policy', 0.5)
                    logger.info(f"Temperature: {response_policy}")
                except Exception as e:
                    logger.warning(f"Could not fetch response_policy: {e}, using default 0.5")

                # Build model settings with proper fields
                model_settings_kwargs: dict = {
                    'temperature': response_policy,
                }

                if ENABLE_EXTENDED_THINKING:
                    from google.genai.types import ThinkingConfigDict
                    model_settings_kwargs['google_thinking_config'] = ThinkingConfigDict(
                        include_thoughts=True
                    )
                    logger.info(f"🧠 Extended thinking ENABLED for this request")
                else:
                    logger.info(f"🧠 Extended thinking DISABLED for this request")

                if cache_name:
                    model_settings_kwargs['google_cached_content'] = cache_name

                model_settings = GoogleModelSettings(**model_settings_kwargs)

                logger.info(f"Agent.iter() call: message='{message[:80]}...', "
                            f"history={len(pydantic_messages)}, cache={cache_name or 'none'}")

                # Check token rate limit before calling Gemini API
                # Estimate: ~500 tokens for system prompt + message history + current message
                estimated_tokens = 500 + (len(pydantic_messages) * 100) + len(message)
                logger.info(f"⏳ Checking token rate limit (estimated: {estimated_tokens} tokens)...")

                from shared.gemini_token_limiter import get_gemini_token_limiter
                token_limiter = get_gemini_token_limiter()

                try:
                    await token_limiter.wait_for_tokens(estimated_tokens)
                    logger.info(f"✅ Token rate limit check passed")
                except TimeoutError as e:
                    logger.error(f"❌ Token rate limit timeout: {e}")
                    yield f"data: {json.dumps({'error': 'Service temporarily rate limited. Please try again in a moment.'})}\n\n"
                    return

                # Retry logic for rate limiting (429 errors)
                max_retries = 3
                retry_attempt = 0
                last_error = None
                run = None

                while retry_attempt < max_retries:
                    try:
                        # Determine whether to pass message_history:
                        # - Cache active: ALWAYS pass message_history (system prompt in cache)
                        # - No cache, first message: DON'T pass (use Agent.system_prompt)
                        # - No cache, follow-up: PASS (includes prepended system prompt)
                        use_message_history = cache_name is not None or has_chat_history

                        if use_message_history:
                            async with agent.iter(
                                message,
                                message_history=pydantic_messages,
                                deps=session_deps,
                                model_settings=model_settings
                            ) as run:
                                from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
                                async for event in run:
                                    logger.debug(f"Event: {type(event).__name__}")
                                break
                        else:
                            # First message, no cache: use Agent.system_prompt
                            async with agent.iter(
                                message,
                                deps=session_deps,
                                model_settings=model_settings
                            ) as run:
                                from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
                                async for event in run:
                                    logger.debug(f"Event: {type(event).__name__}")
                                break

                    except Exception as e:
                        error_str = str(e)
                        last_error = e
                        
                        # Check if this is a 429 rate limit error
                        if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str or 'quota' in error_str.lower():
                            retry_attempt += 1
                            if retry_attempt < max_retries:
                                # Extract retry delay from error if available
                                retry_delay = 10  # Default 10 seconds
                                if 'retry' in error_str.lower():
                                    # Try to extract delay from error message
                                    match = re.search(r'(\d+\.?\d*)\s*s', error_str)
                                    if match:
                                        retry_delay = float(match.group(1))
                                
                                logger.warning(f"⚠️ Rate limit hit (429) - Attempt {retry_attempt}/{max_retries}")
                                logger.warning(f"⏳ Retrying in {retry_delay:.1f} seconds...")
                                await asyncio.sleep(retry_delay)
                                continue
                            else:
                                logger.error(f"❌ Rate limit exceeded after {max_retries} retries")
                                raise
                        else:
                            # Not a rate limit error - re-raise immediately
                            raise

                # After iteration completes, get final result
                logger.info("🔍 Agent iteration completed, extracting response from all_messages()...")
                try:
                    # Get all messages from the run (this is the correct API for agent.iter())
                    all_messages = run.all_messages()
                    logger.info(f"📋 Total messages in conversation: {len(all_messages)}")

                    # 📁 UPLOAD AGENT RESPONSE TO S3 FOR DOWNLOAD (if enabled)
                    enable_s3_upload = os.getenv("ENABLE_RAG_S3_UPLOAD", "false").lower() == "true"
                    
                    if enable_s3_upload:
                        try:
                            from ..tools.knowledge_tools import _upload_agent_response_to_s3
                            agent_s3_download_url = await _upload_agent_response_to_s3(session_id, all_messages, run)
                            if agent_s3_download_url:
                                logger.info(f"📁 Agent response uploaded to S3: {agent_s3_download_url}")
                            else:
                                logger.warning("⚠️ Failed to upload agent response to S3")
                        except Exception as s3_error:
                            logger.error(f"❌ Agent S3 upload failed: {s3_error}")
                            # Continue without S3 upload - don't block the response
                    else:
                        logger.debug("📁 Agent S3 upload disabled (ENABLE_RAG_S3_UPLOAD=false)")

                    # DEBUG: Log all messages structure
                    if not all_messages:
                        logger.error("🚨 CRITICAL: all_messages is EMPTY!")
                    else:
                        logger.info("=" * 100)
                        logger.info("🔍 DEBUG: all_messages structure")
                        logger.info("=" * 100)
                        for i, msg in enumerate(all_messages):
                            logger.info(f"Message {i}: {type(msg).__name__}")
                            if hasattr(msg, 'parts'):
                                logger.info(f"  Parts: {len(msg.parts)}")
                                for j, part in enumerate(msg.parts):
                                    part_type = type(part).__name__
                                    logger.info(f"    Part {j}: {part_type}")
                                    if hasattr(part, 'content'):
                                        content = getattr(part, 'content', '')
                                        content_len = len(str(content))
                                        logger.info(f"      Content length: {content_len}")
                                        if content_len > 0:
                                            logger.info(f"      Preview: {str(content)[:100]}...")
                        logger.info("=" * 100)

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

                    # 🚨 CRITICAL: Check if request_human_agent_connection was called
                    # If so, bypass model response and stream tool response directly
                    tool_response_found = False
                    if 'request_human_agent_connection' in tool_calls_made:
                        logger.warning("🚨 DETECTED: request_human_agent_connection tool was called")
                        logger.warning("🚨 BYPASSING model response - streaming tool response directly")
                        
                        # Extract tool result from all_messages
                        # In Pydantic AI, tool results appear in messages after the tool call
                        logger.info("🔍 Searching for tool response in all_messages...")
                        logger.info(f"📊 Total messages: {len(all_messages)}")
                        
                        # Log all messages and parts for debugging
                        for i, msg in enumerate(all_messages):
                            msg_type = type(msg).__name__
                            logger.info(f"   Message {i}: {msg_type}")
                            if hasattr(msg, 'parts'):
                                logger.info(f"     Parts count: {len(msg.parts)}")
                                for j, part in enumerate(msg.parts):
                                    part_type = type(part).__name__
                                    logger.info(f"       Part {j}: {part_type}")
                                    if isinstance(part, TextPart):
                                        text_content = getattr(part, 'content', '')
                                        logger.info(f"         Content length: {len(text_content)}")
                                        logger.info(f"         Content: {text_content[:150]}...")
                        
                        # First pass: Look for exact tool response messages
                        for i, msg in enumerate(all_messages):
                            if hasattr(msg, 'parts'):
                                for j, part in enumerate(msg.parts):
                                    # Check if this is a text part that contains the tool result
                                    if isinstance(part, TextPart):
                                        text_content = getattr(part, 'content', '')
                                        
                                        # Check if this looks like a tool result (not model elaboration)
                                        # Tool results from request_human_agent_connection are short and specific
                                        if text_content and ('Human Agent support is currently not available' in text_content or 
                                                           'Connected to human agent' in text_content):
                                            logger.info(f"✅ Extracted tool response (exact match): {text_content[:100]}...")
                                            full_response = text_content
                                            tool_response_found = True
                                            logger.info(f"🚨 Using tool response directly, bypassing model elaboration")
                                            break
                            if tool_response_found:
                                break
                            
                            # Second pass: If not found, look for tool response keyword patterns
                            if not tool_response_found:
                                logger.warning("⚠️ Exact tool response not found, looking for keyword-based tool responses...")
                                # Define specific keywords that indicate actual tool responses (not model elaboration)
                                tool_response_keywords = [
                                    'human agent support',
                                    'connected to',
                                    'escalat',  # matches: escalated, escalation
                                    'support is currently',
                                    'connecting you',
                                ]
                                for i, msg in enumerate(all_messages):
                                    if hasattr(msg, 'parts'):
                                        for j, part in enumerate(msg.parts):
                                            if isinstance(part, TextPart):
                                                text_content = getattr(part, 'content', '')
                                                # Check for tool response keywords (NOT just length-based heuristic)
                                                # This prevents matching regular model responses like greetings
                                                text_lower = text_content.lower()
                                                has_tool_keyword = any(keyword in text_lower for keyword in tool_response_keywords)

                                                if text_content and has_tool_keyword and len(text_content) < 200:
                                                    logger.info(f"✅ Found keyword-matched tool response: {text_content[:100]}...")
                                                    full_response = text_content
                                                    tool_response_found = True
                                                    logger.info(f"🚨 Using keyword-matched tool response")
                                                    break
                                    if tool_response_found:
                                        break
                            
                            # If still not found, log warning
                            if not tool_response_found:
                                logger.error("❌ CRITICAL: Tool response not found in any messages!")
                                logger.error(f"❌ Tool was called but response could not be extracted")
                                logger.error(f"❌ This will cause model to generate its own response instead of using tool response")

                    # Extract assistant response and tool calls (SKIP if tool response was found)
                    # NOTE: This MUST run for ALL cases (tools called or not)
                    logger.info(f"🔍 DIAGNOSTIC: tool_response_found = {tool_response_found}, entering extraction if block = {not tool_response_found}")
                    if not tool_response_found:
                        logger.info(f"✅ EXTRACTION LOOP STARTING - tool_response_found is FALSE, proceeding with TextPart extraction")
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
                                    
                                    # DEBUG: Log ALL part types and their full class info
                                    logger.info(f"     🔍 PART DEBUG: {part_type}")
                                    logger.info(f"     🔍 Full class: {type(part)}")
                                    logger.info(f"     🔍 Module: {type(part).__module__}")
                                    
                                    # Check for any thinking-related attributes
                                    part_attrs = dir(part)
                                    thinking_attrs = [attr for attr in part_attrs if 'think' in attr.lower()]
                                    if thinking_attrs:
                                        logger.info(f"     🧠 Thinking-related attributes: {thinking_attrs}")
                                    
                                    # Check for content attribute and log its type/length
                                    if hasattr(part, 'content'):
                                        content = getattr(part, 'content', '')
                                        logger.info(f"     📝 Content type: {type(content)}, length: {len(str(content))}")
                                        if len(str(content)) > 1000:  # Large content might be thinking
                                            logger.info(f"     🧠 LARGE CONTENT DETECTED - might be thinking: {str(content)[:200]}...")

                                    # 🧠 LOG EXTENDED THINKING (if present)
                                    if part_type == 'ThinkingPart':
                                        thinking_content = getattr(part, 'content', '')
                                        logger.info("=" * 100)
                                        logger.info("🧠 MODEL EXTENDED THINKING (Reasoning Process)")
                                        logger.info("=" * 100)
                                        
                                        # Handle potentially long thinking content by chunking it
                                        if thinking_content:
                                            # Split into chunks to avoid OTEL truncation
                                            chunk_size = 2000  # 2KB chunks
                                            thinking_lines = thinking_content.split('\n')
                                            
                                            logger.info(f"🧠 THINKING CONTENT LENGTH: {len(thinking_content)} chars, {len(thinking_lines)} lines")
                                            
                                            # ALSO use print() to bypass OTEL limitations
                                            print("=" * 100)
                                            print("🧠 MODEL EXTENDED THINKING (Reasoning Process) - DIRECT PRINT")
                                            print("=" * 100)
                                            print(thinking_content)
                                            print("=" * 100)
                                            
                                            current_chunk = ""
                                            chunk_num = 1
                                            
                                            for line in thinking_lines:
                                                if len(current_chunk) + len(line) + 1 > chunk_size:
                                                    # Log current chunk
                                                    if current_chunk.strip():
                                                        logger.info(f"🧠 THINKING CHUNK {chunk_num}:")
                                                        logger.info(current_chunk)
                                                        chunk_num += 1
                                                    current_chunk = line + '\n'
                                                else:
                                                    current_chunk += line + '\n'
                                            
                                            # Log final chunk
                                            if current_chunk.strip():
                                                logger.info(f"🧠 THINKING CHUNK {chunk_num}:")
                                                logger.info(current_chunk)
                                        else:
                                            logger.warning("🧠 ThinkingPart found but content is empty!")
                                        
                                        logger.info("=" * 100)
                                    
                                    # 🧠 ALTERNATIVE: Check for thinking in other part types
                                    elif hasattr(part, 'thinking') or hasattr(part, 'thoughts'):
                                        logger.info("🧠 ALTERNATIVE THINKING ATTRIBUTE FOUND!")
                                        thinking_attr = getattr(part, 'thinking', None) or getattr(part, 'thoughts', None)
                                        if thinking_attr:
                                            print("=" * 100)
                                            print("🧠 ALTERNATIVE THINKING CONTENT - DIRECT PRINT")
                                            print("=" * 100)
                                            print(thinking_attr)
                                            print("=" * 100)

                                    # Extract text from TextPart
                                    if isinstance(part, TextPart):
                                        text_content = getattr(part, 'content', '')
                                        text_part_index = [p for p in msg.parts[:j+1] if isinstance(p, TextPart)].__len__()
                                        is_last_text_part = text_part_index == len(text_parts)

                                        logger.info(f"     🔍 TextPart {text_part_index}/{len(text_parts)}: {len(text_content)} chars")
                                        logger.info(f"        Preview: {text_content[:80]}...")

                                        if text_content:
                                            # Skip if we already have tool response
                                            if 'request_human_agent_connection' in tool_calls_made and full_response:
                                                logger.info(f"     ⏭️ Skipping TextPart (using tool response instead)")
                                                continue

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

                    logger.info(f"Agent completed with {tool_call_count} tool calls")

                    # Monitor tool call compliance
                    if tool_call_count == 0 and message.strip():
                        greeting_patterns = ["hi", "hello", "hey", "good morning", "good afternoon", "greetings"]
                        is_greeting = any(g in message.lower() for g in greeting_patterns)

                        emoji_pattern = re.compile(
                            r'^[\U0001F600-\U0001F64F'
                            r'\U0001F300-\U0001F5FF'
                            r'\U0001F680-\U0001F6FF'
                            r'\U0001F1E0-\U0001F1FF'
                            r'\U00002702-\U000027B0'
                            r'\U0000FE00-\U0000FE0F'
                            r'\U0000200D'
                            r'\U00002600-\U000026FF'
                            r'\U0000231A-\U0000231B'
                            r'\U00002934-\U00002935'
                            r'\U000025AA-\U000025FE'
                            r'\U00002B05-\U00002B07'
                            r'\U00002B1B-\U00002B1C'
                            r'\U00002B50'
                            r'\U00002B55'
                            r'\U0001F900-\U0001F9FF'
                            r'\U0001FA00-\U0001FA6F'
                            r'\U0001FA70-\U0001FAFF'
                            r'\s]+$'
                        )
                        if not is_greeting and emoji_pattern.match(message.strip()):
                            is_greeting = True

                        if not is_greeting:
                            logger.error(f"TOOL CALL REQUIREMENT NOT MET: query='{message[:80]}', tools=0")
                            logger.error(f"🚨 CRITICAL: Agent should have called search_knowledge_base for non-greeting query")
                            logger.error(f"🚨 Response was: {full_response[:100]}...")
                            logger.error(f"🚨 This indicates the agent is not following the mandatory tool-calling requirement")

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

                # 🚨 CRITICAL: Remove metadata that model may have added
                # Strip out [Time-to-Solve: X mins] or similar timing information
                full_response = re.sub(r'\[Time-to-Solve:.*?\]', '', full_response).strip()
                logger.info(f"✅ Removed Time-to-Solve metadata if present")
                
                # Add agent download link if S3 upload succeeded
                if agent_s3_download_url:
                    agent_download_section = f"\n\n🤖 **Agent Response Details**: [Download Complete Response]({agent_s3_download_url})"
                    full_response += agent_download_section
                    logger.info(f"📁 Added agent download link to response: {agent_s3_download_url}")

                # 🚨 CRITICAL: Filter out elaboration from tool responses
                # If response contains "Human Agent support is currently not available" with elaboration,
                # extract ONLY the core message
                if "Human Agent support is currently not available" in full_response or \
                   "human agent support is currently" in full_response.lower():
                    logger.warning("🚨 Detected HIL unavailable message with elaboration - filtering...")
                    # Extract only the exact message, remove all elaboration
                    # Look for the exact phrase and extract just that
                    match = re.search(r'Human Agent support is currently not available[!.]?', full_response, re.IGNORECASE)
                    if match:
                        full_response = match.group(0)
                        logger.info(f"✅ Filtered response to exact message: {full_response}")
                    else:
                        # Fallback: just use the exact message
                        full_response = "Human Agent support is currently not available."
                        logger.warning(f"⚠️ Could not find exact match, using fallback: {full_response}")

                # 📤 BROADCAST AI RESPONSE TO ADMIN CHANNEL (so admins see AI responses in real-time)
                try:
                    from shared.redis_pubsub_manager import broadcast_event_to_all_agents
                    from datetime import datetime

                    ai_response_event = {
                        "type": "bot_message",
                        "message_id": f"bot-{session_id}-{int(time.time() * 1000)}",
                        "session_id": session_id,
                        "text": full_response,
                        "sender": "bot",
                        "timestamp": datetime.utcnow().isoformat(),
                        "tool_calls": tool_call_count
                    }

                    broadcast_result = await broadcast_event_to_all_agents(ai_response_event)
                    logger.info(f"📤 Broadcasted bot response to admins on agent:events:broadcast")
                    logger.info(f"📤 Broadcast result: {broadcast_result}")
                except Exception as broadcast_error:
                    logger.error(f"❌ Failed to broadcast bot response to admins: {broadcast_error}")
                    # Continue anyway - don't block customer response if broadcast fails

                # Break response into chunks for streaming to customer (500 chars per chunk for smooth experience)
                chunk_size = 500
                chunks = [full_response[i:i+chunk_size] for i in range(0, len(full_response), chunk_size)]
                logger.info(f"🔍 DEBUG: Created {len(chunks)} chunks for customer streaming")

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

                        # Note: Removed bot_message_chunk broadcasting to admin - using only final bot_message

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
                logger.info(f"   Source: Gemini FileStore ({MODEL_NAME} model)")
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

            # Post response to Redis channels instead of direct SSE streaming
            logger.info("=" * 80)
            logger.info("📤 POSTING RESPONSE TO REDIS CHANNELS")
            logger.info(f"   Session ID: {session_id}")
            logger.info(f"   Response Length: {len(full_response)} characters")
            logger.info(f"   Tool Calls: {tool_call_count}")
            logger.info("=" * 80)
            
            # Create response event for customer channel
            customer_response_event = {
                "type": "ai_response",
                "session_id": session_id,
                "content": full_response,
                "chunk_count": chunk_count,
                "tool_calls": tool_call_count,
                "timestamp": int(time.time()),
                "grounding_sources": "Gemini FileStore",
                "response_format": "HTML with citations"
            }
            
            # Post to customer's Redis channel
            try:
                customer_result = await broadcast_event_to_session(session_id, customer_response_event)
                logger.info(f"✅ Posted AI response to customer channel: customer:events:{session_id}")
                logger.info(f"   Broadcast result: {customer_result}")
            except Exception as e:
                logger.error(f"❌ Failed to post to customer channel: {e}")
            
            # Create response event for admin channel (if agent is assigned)
            try:
                assigned_agent_id = await get_assigned_agent(session_id)
                if assigned_agent_id:
                    admin_response_event = {
                        "type": "ai_response",
                        "session_id": session_id,
                        "content": full_response,
                        "chunk_count": chunk_count,
                        "tool_calls": tool_call_count,
                        "timestamp": int(time.time()),
                        "grounding_sources": "Gemini FileStore",
                        "response_format": "HTML with citations",
                        "message": f"AI responded to customer in session {session_id}"
                    }
                    
                    # Post to assigned agent's channel
                    admin_result = await broadcast_event_to_agent(assigned_agent_id, admin_response_event)
                    logger.info(f"✅ Posted AI response to agent channel: agent:events:{assigned_agent_id}")
                    logger.info(f"   Broadcast result: {admin_result}")
                    
                    # Also post to broadcast channel for all admins
                    broadcast_result = await broadcast_event_to_all_agents(admin_response_event)
                    logger.info(f"✅ Posted AI response to admin broadcast channel: agent:events:broadcast")
                    logger.info(f"   Broadcast result: {broadcast_result}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to post to admin channels: {e}")

            # Send completion signal via Redis (for SSE to pick up)
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
            
            # Post completion event to Redis channels
            completion_data = {
                "type": "complete",
                "session_id": session_id,
                "total_chunks": chunk_count,
                "total_length": len(full_response),
                "tool_calls": tool_call_count,
                "grounding_sources": "Gemini FileStore",
                "response_format": "HTML with citations",
                "completion_status": "success",
                "timestamp": int(time.time())
            }
            
            # Post completion to customer channel
            try:
                await broadcast_event_to_session(session_id, completion_data)
                logger.info(f"✅ Posted completion event to customer channel")
            except Exception as e:
                logger.error(f"❌ Failed to post completion to customer channel: {e}")
            
            # Post completion to admin channels
            try:
                assigned_agent_id = await get_assigned_agent(session_id)
                if assigned_agent_id:
                    await broadcast_event_to_agent(assigned_agent_id, completion_data)
                    await broadcast_event_to_all_agents(completion_data)
                    logger.info(f"✅ Posted completion event to admin channels")
            except Exception as e:
                logger.warning(f"⚠️ Failed to post completion to admin channels: {e}")
            
            # Yield completion signal for SSE (SSE will pick up from Redis channels)
            completion_json = json.dumps(completion_data, ensure_ascii=False)
            yield f"data: {completion_json}\n\n"

            logger.info(f"✅ Streaming completed for session: {session_id}")
            logger.info(f"📊 Total chunks sent: {chunk_count}")
            logger.info(f"📝 Total response length: {len(full_response)} characters")

            # Track token usage after streaming completes
            try:
                await self._track_token_usage(session_id, user_email, full_response, tool_call_count, run=run)
            except Exception as token_error:
                logger.error(f"❌ Error tracking token usage: {token_error}")

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

    async def _track_token_usage(self, session_id: str, user_email: str, response_text: str, tool_call_count: int, run=None):
        """Track token usage after agent response completes.
        
        Args:
            session_id: Session ID
            user_email: User email
            response_text: Response text
            tool_call_count: Number of tool calls made
            run: Pydantic AI run object (optional) - if provided, uses actual token counts from Gemini
        """
        try:
            from ..core.token_tracker import track_gemini_usage
            import os

            model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

            # Try to get actual token usage from run object first
            actual_prompt_tokens = 0
            actual_completion_tokens = 0
            actual_total_tokens = 0
            
            if run:
                try:
                    # Get actual usage from Pydantic AI run object
                    usage = run.usage()
                    if usage:
                        # Extract token counts from usage object
                        actual_prompt_tokens = getattr(usage, 'input_tokens', 0) or 0
                        actual_completion_tokens = getattr(usage, 'output_tokens', 0) or 0
                        actual_total_tokens = getattr(usage, 'total_tokens', 0) or (actual_prompt_tokens + actual_completion_tokens)
                        
                        logger.info(f"✅ Got ACTUAL token counts from Gemini API:")
                        logger.info(f"   Input tokens: {actual_prompt_tokens}")
                        logger.info(f"   Output tokens: {actual_completion_tokens}")
                        logger.info(f"   Total tokens: {actual_total_tokens}")
                except Exception as usage_error:
                    logger.warning(f"⚠️ Could not extract usage from run object: {usage_error}")
                    actual_prompt_tokens = 0
                    actual_completion_tokens = 0
                    actual_total_tokens = 0
            
            # If we got actual tokens, use them; otherwise fall back to estimates
            if actual_total_tokens > 0:
                prompt_tokens = actual_prompt_tokens
                completion_tokens = actual_completion_tokens
                total_tokens = actual_total_tokens
                token_source = "ACTUAL (from Gemini API)"
            else:
                # Fallback: Estimate token usage based on response length
                # Gemini token estimation: ~4 chars = 1 token (rough estimate)
                response_chars = len(response_text)
                completion_tokens = max(1, response_chars // 4)
                
                # Estimate prompt tokens based on conversation history
                prompt_tokens = 500  # Default estimate for conversation history
                
                # Total tokens = prompt + completion
                total_tokens = prompt_tokens + completion_tokens
                token_source = "ESTIMATED (from response length)"

            logger.info(f"📊 Token tracking source: {token_source}")
            logger.info(f"   Prompt tokens: {prompt_tokens}")
            logger.info(f"   Completion tokens: {completion_tokens}")
            logger.info(f"   Total tokens: {total_tokens}")

            success = await track_gemini_usage(
                prompt_tokens=prompt_tokens,
                candidates_tokens=completion_tokens,
                session_id=session_id,
                api_call_type='agent_stream',
                model=model_name
            )

            if success:
                logger.info(f"✅ Tracked {total_tokens} tokens for session {session_id[:8]}... ({token_source})")
            else:
                logger.error(f"❌ Failed to track token usage for session {session_id}")

        except Exception as e:
            logger.error(f"❌ Error tracking token usage: {e}", exc_info=True)

# Global streaming service instance
streaming_service = StreamingService()
