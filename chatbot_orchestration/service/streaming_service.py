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
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart, SystemPromptPart, BuiltinToolCallPart, BuiltinToolReturnPart, ToolCallPart, ToolReturnPart
from shared.otel_logger import get_otel_logger, set_session_id

from ..core.dependencies import ChatSessionDeps
from ..core.ai import get_genai_client
from ..core.config import settings
from .session_manager import session_state_manager
from .agent_manager import agent_manager
from shared.profiling import trace_phase, PipelineTimer

logger = get_otel_logger("streaming_service", "chatbot-orchestration")

# Feature flags
ENABLE_EXTENDED_THINKING = os.getenv("ENABLE_EXTENDED_THINKING", "false").lower() == "true"

class StreamingService:
    """Handles streaming responses for the chatbot."""

    def __init__(self):
        from ..dao.chat_dao import ChatDAO
        self.chat_dao = ChatDAO()

    async def _get_user_display_id(self, session_id: str) -> str:
        """Get the User-N display ID for a session based on its ROW_NUMBER in chat_sessions."""
        try:
            from shared.sqlalchemy_db import get_db_session
            from sqlalchemy import text
            async with get_db_session() as db_session:
                result = await db_session.execute(
                    text("""
                        SELECT 'User-' || row_num as user_display_id
                        FROM (
                            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at ASC) as row_num
                            FROM chat_sessions
                        ) ranked
                        WHERE id = CAST(:session_id AS UUID)
                    """),
                    {"session_id": session_id}
                )
                row = result.fetchone()
                return row[0] if row else "User"
        except Exception as e:
            logger.warning(f"Failed to get user_display_id for {session_id}: {e}")
            return "User"

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

            # Pipeline performance timer - tracks each phase
            pipeline_timer = PipelineTimer(session_id)

            # 📁 UPLOAD AGENT REQUEST TO S3 (if enabled)
            agent_request_download_url = None
            enable_s3_upload = os.getenv("ENABLE_RAG_S3_UPLOAD", "true").lower() == "true"
            
            if enable_s3_upload:
                logger.info("📁 Agent S3 upload is ENABLED - uploading agent request data...")
                try:
                    from ..tools.knowledge_tools import _upload_agent_request_to_s3
                    
                    # Get conversation history for context
                    chat_history = await session_state_manager.get_chat_history(session_id)
                    
                    agent_request_download_url = await _upload_agent_request_to_s3(
                        session_id, 
                        message, 
                        chat_history
                    )
                    if agent_request_download_url:
                        logger.info(f"📁 ✅ Agent request uploaded to S3: {agent_request_download_url}")
                    else:
                        logger.warning("📁 ⚠️ Failed to upload agent request to S3 (returned None)")
                except Exception as s3_error:
                    logger.error(f"📁 ❌ Agent request S3 upload failed: {s3_error}")
                    # Continue without S3 upload - don't block the response
            else:
                logger.info("📁 Agent S3 upload is DISABLED (ENABLE_RAG_S3_UPLOAD=false or not set)")

            pipeline_timer.mark("s3_request_upload")

            # Session setup (PG + Redis DB6) is done at page load via /validate-chat
            # Here we only update activity and proceed with the response
            from shared.redis_chat_store import get_chat_store
            chat_store = get_chat_store()

            # Update session activity
            session_state_manager.update_session_activity(session_id)
            session_state_manager.set_streaming_state(session_id, True)

            # PG18: session_id IS the database PK — single identifier
            session_deps = ChatSessionDeps(session_id=session_id)
            logger.info(f"✅ Session dependencies created: {session_id}")

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

            pipeline_timer.mark("session_setup_and_history")

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
                    
                    # PG18: session_id IS the database PK
                    if session_id:
                            # Call configuration service to assign agent
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                response = await client.post(
                                    endpoint_url,
                                    json={"session_id": session_id}
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
                                        verify_result = await verify_db.execute(sql_text(verify_query), {"session_id": session_id})
                                        verify_row = verify_result.mappings().first()
                                        if verify_row:
                                            logger.info(f"Verified agent assignment in database: {verify_row['agent_email']} (ID: {verify_row['agent_id']})")
                                        else:
                                            logger.warning(f"Agent assignment not found in database yet for session {session_id}")
                                    
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

                                    # Save system message indicating human agent request
                                    await session_state_manager.save_message(
                                        session_id=session_id,
                                        role="assistant",
                                        content=f"Human agent requested. Agent {assigned_agent} has been assigned to this chat.",
                                        metadata={"type": "human_agent_request", "assigned_agent": assigned_agent}
                                    )

                                    # Broadcast session to agent with all messages
                                    from shared.redis_pubsub_manager import broadcast_event_to_agent
                                    from datetime import datetime
                                    
                                    # Get session details and messages from Redis
                                    redis_session = await chat_store.get_session(session_id)
                                    redis_messages = await chat_store.get_messages(session_id)

                                    if redis_session:

                                        messages = []
                                        role_to_sender = {"user": "customer", "assistant": "bot"}
                                        for i, msg in enumerate(redis_messages):
                                            raw_role = msg.get('role', '')
                                            messages.append({
                                                "id": str(i),
                                                "text": msg.get('content', ''),
                                                "sender": role_to_sender.get(raw_role, raw_role),
                                                "timestamp": msg.get('created_at', datetime.utcnow().isoformat()),
                                                "session_id": session_id
                                            })

                                        # Get the canonical User-N display ID from PG row number
                                        user_display_id = await self._get_user_display_id(session_id)

                                        # Build session event
                                        session_event = {
                                            "type": "session_update",
                                            "data": {
                                                "id": session_id,
                                                "session_uuid": session_id,
                                                "customer_name": user_display_id,
                                                "user_display_id": user_display_id,
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
                                    
                                    # Don't send any confirmation message - UI will show waiting indicator
                                    # The chat_assigned event will trigger the waiting state
                                    
                                    # Stream empty response to complete the stream properly
                                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                                    logger.info(f"✅ Agent assigned and stream completed")
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
                                WHERE sa.session_id = CAST(:session_id AS UUID)
                                AND sa.status = 'active'
                                AND u.is_active = true
                                LIMIT 1
                            """
                            result = await db_session.execute(text(query), {"session_id": session_id})
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
                    assigned_agent_id = str(assigned_agent_id) if isinstance(assigned_agent_id, bytes) else assigned_agent_id
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

            # 📤 BROADCAST USER MESSAGE TO ADMIN CHANNEL (so admins see user messages in real-time)
            try:
                from shared.redis_pubsub_manager import broadcast_event_to_all_agents
                from datetime import datetime

                # Get the canonical User-N display ID from PG row number
                user_display_id = await self._get_user_display_id(session_id)

                user_message_event = {
                    "type": "customer_message",
                    "message_id": f"user-{session_id}-{int(time.time() * 1000)}",
                    "session_id": session_id,
                    "text": message,
                    "sender": "user",
                    "timestamp": datetime.utcnow().isoformat(),
                    "user_display_id": user_display_id,
                    "customer_name": user_display_id
                }

                await broadcast_event_to_all_agents(user_message_event)
                logger.info(f"📤 Broadcasted user message to admins on agent:events:broadcast")
            except Exception as broadcast_error:
                logger.error(f"❌ Failed to broadcast user message to admins: {broadcast_error}")

            pipeline_timer.mark("pre_agent_checks")

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
                logger.info(f"🔧 Agent tools: search_knowledge_base (pgvector)")

                # Log what the agent is receiving
                logger.info("=" * 100)
                logger.info("🤖 AGENT INPUT SUMMARY")
                logger.info(f"   Current User Message: {message[:150]}...")
                logger.info(f"   Message History Length: {len(pydantic_messages)} messages")
                logger.info(f"   Context Window: Full conversation context provided")
                logger.info(f"   Available Tools: search_knowledge_base (pgvector)")
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
                                # Return clean error instead of re-raising
                                error_data = {
                                    "type": "error",
                                    "error_code": "RATE_LIMIT_EXCEEDED",
                                    "message": "I'm currently experiencing high demand. Please try again in a few moments.",
                                    "session_id": session_id,
                                    "timestamp": int(time.time())
                                }
                                json_response = json.dumps(error_data, ensure_ascii=False)
                                yield f"data: {json_response}\n\n"
                                return
                        else:
                            # Not a rate limit error - return clean error instead of re-raising
                            logger.error(f"❌ Agent.iter() setup failed: {str(e)}")
                            error_data = {
                                "type": "error",
                                "error_code": "AGENT_SETUP_ERROR", 
                                "message": "I apologize, but I encountered an error while setting up the response. Please try again.",
                                "session_id": session_id,
                                "timestamp": int(time.time())
                            }
                            json_response = json.dumps(error_data, ensure_ascii=False)
                            yield f"data: {json_response}\n\n"
                            return

                # Check if we successfully got a run object
                if run is None:
                    logger.error("❌ Failed to create agent run after all retries")
                    error_data = {
                        "type": "error",
                        "error_code": "AGENT_INITIALIZATION_FAILED",
                        "message": "I apologize, but I'm unable to process your request right now. Please try again later.",
                        "session_id": session_id,
                        "timestamp": int(time.time())
                    }
                    json_response = json.dumps(error_data, ensure_ascii=False)
                    yield f"data: {json_response}\n\n"
                    return

                pipeline_timer.mark("agent_inference")

                # After iteration completes, get final result
                logger.info("🔍 Agent iteration completed, extracting response from all_messages()...")
                try:
                    # Get all messages from the run (this is the correct API for agent.iter())
                    all_messages = run.all_messages()
                    logger.info(f"📋 Total messages in conversation: {len(all_messages)}")

                    # 📁 UPLOAD AGENT RESPONSE TO S3 FOR DOWNLOAD (if enabled)
                    enable_s3_upload = os.getenv("ENABLE_RAG_S3_UPLOAD", "true").lower() == "true"
                    
                    logger.info(f"🔍 DEBUG: Agent S3 upload - ENABLE_RAG_S3_UPLOAD = '{os.getenv('ENABLE_RAG_S3_UPLOAD', 'NOT_SET')}'")
                    logger.info(f"🔍 DEBUG: Agent S3 upload - enable_s3_upload = {enable_s3_upload}")
                    
                    if enable_s3_upload:
                        logger.info("📁 Agent S3 upload is ENABLED - attempting upload...")
                        try:
                            from ..tools.knowledge_tools import _upload_agent_response_to_s3
                            agent_s3_download_url = await _upload_agent_response_to_s3(session_id, all_messages, run)
                            if agent_s3_download_url:
                                logger.info(f"📁 ✅ Agent response uploaded to S3: {agent_s3_download_url}")
                            else:
                                logger.warning("📁 ⚠️ Failed to upload agent response to S3 (returned None)")
                        except Exception as s3_error:
                            logger.error(f"📁 ❌ Agent S3 upload failed: {s3_error}")
                            # Continue without S3 upload - don't block the response
                    else:
                        logger.info("📁 Agent S3 upload is DISABLED (ENABLE_RAG_S3_UPLOAD=false or not set)")

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
                    logger.info(f"🔧 Tools available: search_knowledge_base (pgvector)")
                    sys.stdout.flush()

                    tool_calls_made = []
                    for i, msg in enumerate(all_messages):
                        msg_type = type(msg).__name__
                        logger.info(f"📌 Message {i}: {msg_type}")

                        # Log tool calls and grounding results
                        if hasattr(msg, 'parts'):
                            for j, part in enumerate(msg.parts):
                                part_type = type(part).__name__

                                # Detect & log tool CALLS
                                if isinstance(part, (BuiltinToolCallPart, ToolCallPart)):
                                    tool_name = getattr(part, 'tool_name', 'unknown')
                                    tool_calls_made.append(tool_name)
                                    tool_args = getattr(part, 'args', {})
                                    logger.info(f"   ✅ Tool called: {tool_name}")
                                    logger.info(f"   🔍 [TOOL_QUERY] Args: {tool_args}")

                                # Detect & log tool RETURNS
                                elif isinstance(part, (BuiltinToolReturnPart, ToolReturnPart)):
                                    tool_name = getattr(part, 'tool_name', 'unknown')
                                    content = getattr(part, 'content', '')
                                    logger.info("=" * 100)
                                    logger.info(f"📚 [RAG_GROUNDING] Tool return from: {tool_name}")
                                    logger.info(f"📚 [RAG_GROUNDING] Content length: {len(str(content))} chars")
                                    logger.info("=" * 100)
                                    # Log full grounding content in chunks to avoid OTEL truncation
                                    content_str = str(content)
                                    chunk_size = 2000
                                    total_chunks = (len(content_str) + chunk_size - 1) // chunk_size
                                    for chunk_idx in range(total_chunks):
                                        chunk = content_str[chunk_idx * chunk_size:(chunk_idx + 1) * chunk_size]
                                        logger.info(f"📚 [RAG_GROUNDING] [{chunk_idx + 1}/{total_chunks}]: {chunk}")
                                    logger.info("=" * 100)

                                # Log text content (model's final answer)
                                elif part_type == 'TextPart' and hasattr(part, 'content'):
                                    content = getattr(part, 'content', '')
                                    preview = content[:200] if len(content) > 200 else content
                                    logger.info(f"   📝 {part_type}: {preview}...")

                    logger.info("=" * 100)
                    logger.info(f"📊 SUMMARY: {len(tool_calls_made)} tools called: {tool_calls_made if tool_calls_made else 'NONE'}")
                    if len(tool_calls_made) == 0 and len(pydantic_messages) > 0:
                        logger.warning("⚠️  WARNING: This is a follow-up (history exists) but NO tools were called!")
                        logger.warning("⚠️  Expected: search_knowledge_base should have been used")
                    logger.info("=" * 100)


                    # Extract assistant response from all_messages
                    if True:
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

                                    # Log pgvector search tool call
                                    if isinstance(part, (BuiltinToolCallPart, ToolCallPart)) and getattr(part, 'tool_name', '') == 'search_knowledge_base':
                                        tool_call_count += 1
                                        logger.info("=" * 80)
                                        logger.info("🔍 PGVECTOR TOOL CALL")
                                        logger.info(f"   Tool Name: {part.tool_name}")
                                        logger.info(f"   Tool Call ID: {getattr(part, 'tool_call_id', 'N/A')}")
                                        logger.info(f"   Args: {getattr(part, 'args', {})}")
                                        logger.info(f"   Tool Call #{tool_call_count} in this response")
                                        logger.info("=" * 80)

                                    # Log pgvector tool return
                                    elif isinstance(part, (BuiltinToolReturnPart, ToolReturnPart)) and getattr(part, 'tool_name', '') == 'search_knowledge_base':
                                        logger.info("=" * 80)
                                        logger.info("📄 PGVECTOR TOOL RESPONSE (GROUNDING DATA)")
                                        logger.info(f"   Tool Name: {part.tool_name}")
                                        logger.info(f"   Tool Call ID: {getattr(part, 'tool_call_id', 'N/A')}")
                                        logger.info(f"   Content Type: {type(part.content).__name__}")
                                        content_str = str(part.content)
                                        logger.info(f"   Content: {content_str[:2000]}")

                                        logger.info("=" * 80)

                                    # Track other tool calls with detailed logging
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
                            logger.error(f"🚨 CRITICAL: Agent should have used search_knowledge_base for non-greeting query")
                            logger.error(f"🚨 Response was: {full_response[:100]}...")
                            logger.error(f"🚨 This indicates the agent is not using the pgvector retrieval tool")

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


            pipeline_timer.mark("response_extraction")

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

                # ================================================================
                # CITATION POST-PROCESSING
                # ================================================================
                # The pgvector tool currently returns formatted text context rather than
                # a structured citation payload, so there is no automatic source
                # URL extraction step here.
                citation_urls = []
                try:
                    logger.info("📎 [CITATION_POST] No structured citation payload available for pgvector tool")

                    if citation_urls:
                        logger.info(f"📎 [CITATION_POST] Found {len(citation_urls)} citation URLs: {citation_urls}")
                        # Replace plain [N] markers with clickable <a> links
                        markers_replaced = 0
                        for i, url in enumerate(citation_urls, 1):
                            plain_marker = f'[{i}]'
                            clickable_link = f'<a href="{url}" target="_blank" rel="noopener noreferrer">[{i}]</a>'
                            if plain_marker in full_response:
                                full_response = full_response.replace(plain_marker, clickable_link)
                                markers_replaced += 1
                                logger.info(f"📎 [CITATION_POST] Replaced {plain_marker} → clickable link to {url}")

                        # Fallback: if no [N] markers were found but we have URLs,
                        # append a sources section so citations are never lost
                        if markers_replaced == 0:
                            logger.warning(f"📎 [CITATION_POST] No [N] markers in response — appending sources section")
                            sources_html = '<p class="citation-sources"><strong>Sources:</strong> '
                            source_links = []
                            for i, url in enumerate(citation_urls, 1):
                                source_links.append(
                                    f'<a href="{url}" target="_blank" rel="noopener noreferrer">[{i}]</a>'
                                )
                            sources_html += ' '.join(source_links) + '</p>'
                            full_response += sources_html
                            logger.info(f"📎 [CITATION_POST] Appended {len(citation_urls)} source links as fallback")
                        else:
                            logger.info(f"📎 [CITATION_POST] Replaced {markers_replaced} inline markers")
                    else:
                        logger.info("📎 [CITATION_POST] No structured citations found in response")
                except Exception as citation_error:
                    logger.warning(f"📎 [CITATION_POST] Citation processing failed (non-fatal): {citation_error}")

                # Add all debug download links if S3 upload succeeded
                download_links = []
                
                # Add agent request link
                if agent_request_download_url:
                    download_links.append(f"[Download Agent Request]({agent_request_download_url})")
                    logger.info(f"📁 ✅ Added agent request download link: {agent_request_download_url}")
                
                # Add agent response link
                if agent_s3_download_url:
                    download_links.append(f"[Download Agent Response]({agent_s3_download_url})")
                    logger.info(f"📁 ✅ Added agent response download link: {agent_s3_download_url}")
                
                if download_links:
                    agent_download_section = f"\n\n📁 **Agent Debug Details**: {' | '.join(download_links)}"
                    full_response += agent_download_section
                    logger.info(f"📁 ✅ Full response now includes agent debug section (total length: {len(full_response)} chars)")
                else:
                    logger.info("📁 ❌ No agent download links added - both URLs are None")

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
                logger.info("📝 MODEL RESPONSE WITH GROUNDING TRUTH")
                logger.info(f"   Session ID: {session_id}")
                logger.info(f"   User Query: {message[:100]}...")
                logger.info(f"   User Email: {user_email}")
                logger.info(f"   Total Tool Calls: {tool_call_count}")
                logger.info(f"   Response Length: {len(full_response)} characters")
                logger.info(f"   Response Chunks: {chunk_count}")
                logger.info("-" * 100)
                logger.info("🔗 GROUNDING TRUTH & DATA SOURCES:")
                logger.info(f"   Source: pgvector knowledge base ({settings.chatbot_model} model)")
                logger.info("   Search Type: Hybrid pgvector + full-text retrieval")
                logger.info("   Processing: Retrieved chunk context formatted by the model")
                logger.info("   Response Format: HTML with proper citations")
                logger.info("   Data Quality: Grounded in vectorized knowledge base chunks")
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
                            "grounding_sources": "pgvector",
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
                "grounding_sources": "pgvector",
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
                        "grounding_sources": "pgvector",
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

            pipeline_timer.mark("save_and_broadcast")
            pipeline_timer.done()

            # Send completion signal via Redis (for SSE to pick up)
            logger.info("=" * 80)
            logger.info("🏁 STREAMING COMPLETION SUMMARY")
            logger.info(f"   Session ID: {session_id}")
            logger.info(f"   User Email: {user_email}")
            logger.info(f"   Total Tool Calls Executed: {tool_call_count}")
            logger.info(f"   Total Response Chunks: {chunk_count}")
            logger.info(f"   Final Response Length: {len(full_response)} characters")
            logger.info("   Grounding Truth: Response based on pgvector search results")
            logger.info("   Primary Data Source: pgvector knowledge base")
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
                "grounding_sources": "pgvector",
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
                # Gather prompt component texts for granular breakdown
                system_prompt_text = agent_manager.get_cached_system_prompt(session_id) or ""
                # Serialize conversation history to plain text for counting
                history_text = ""
                for pmsg in pydantic_messages:
                    for part in getattr(pmsg, 'parts', []):
                        part_content = getattr(part, 'content', '')
                        if part_content and not isinstance(part, SystemPromptPart):
                            history_text += str(part_content) + "\n"
                # Tool definitions text — we can't extract the actual schema Pydantic AI sends to Gemini,
                # so token count is derived as: input_tokens - sys_prompt - history - user_msg
                tool_def_text = "(Actual Gemini tool schema — tokens derived from input_tokens remainder)"

                await self._track_token_usage(
                    session_id, user_email, full_response, tool_call_count,
                    run=run, user_message=message,
                    system_prompt_text=system_prompt_text,
                    history_text=history_text,
                    tool_def_text=tool_def_text
                )

                # Save per-step breakdown from agent run
                if run:
                    try:
                        asyncio.create_task(self._save_agent_run_steps(session_id, run))
                    except Exception as steps_err:
                        logger.warning(f"⚠️ Failed to save agent run steps: {steps_err}")
            except Exception as token_error:
                logger.error(f"❌ Error tracking token usage: {token_error}")

        except Exception as e:
            logger.error(f"❌ Critical error in stream_agent_response: {e}", exc_info=True)
            
            # Return clean JSON error instead of feeding error text back to model
            error_data = {
                "type": "error",
                "error_code": "AGENT_PROCESSING_ERROR",
                "message": "I apologize, but I encountered an error while processing your request. Please try again.",
                "session_id": session_id,
                "timestamp": int(time.time())
            }
            json_response = json.dumps(error_data, ensure_ascii=False)
            yield f"data: {json_response}\n\n"
            
            # Also yield completion signal to close the stream properly
            completion_data = {
                "type": "complete",
                "session_id": session_id,
                "completion_status": "error",
                "timestamp": int(time.time())
            }
            completion_json = json.dumps(completion_data, ensure_ascii=False)
            yield f"data: {completion_json}\n\n"

        finally:
            # Always reset streaming state
            session_state_manager.set_streaming_state(session_id, False)
            logger.info(f"🔄 Streaming state reset for session: {session_id}")

    async def _track_token_usage(self, session_id: str, user_email: str, response_text: str, tool_call_count: int, run=None, user_message: str = "", system_prompt_text: str = "", history_text: str = "", tool_def_text: str = ""):
        """Track token usage after agent response completes.

        Args:
            session_id: Session ID
            user_email: User email
            response_text: Response text
            tool_call_count: Number of tool calls made
            run: Pydantic AI run object (optional) - if provided, uses actual token counts from Gemini
            user_message: The original user message text
            system_prompt_text: The system prompt text for granular breakdown
            history_text: Serialized conversation history text
            tool_def_text: Tool definitions text
        """
        try:
            from ..core.token_tracker import track_gemini_usage_detailed
            import os

            model_name = os.getenv("GEMINI_MODEL_NAME", os.getenv("CHATBOT_MODEL", "gemini-2.5-flash-lite"))

            # Try to get actual token usage from run object first
            input_tokens = 0
            output_tokens = 0

            cache_read_tokens = 0
            cache_write_tokens = 0

            if run:
                try:
                    usage = run.usage()
                    if usage:
                        input_tokens = getattr(usage, 'input_tokens', 0) or 0
                        output_tokens = getattr(usage, 'output_tokens', 0) or 0
                        cache_read_tokens = getattr(usage, 'cache_read_tokens', 0) or 0
                        cache_write_tokens = getattr(usage, 'cache_write_tokens', 0) or 0

                        logger.info(f"✅ Got ACTUAL token counts from Gemini API:")
                        logger.info(f"   Input tokens: {input_tokens}")
                        logger.info(f"   Output tokens: {output_tokens}")
                        logger.info(f"   Cache read tokens: {cache_read_tokens}")
                        logger.info(f"   Cache write tokens: {cache_write_tokens}")
                except Exception as usage_error:
                    logger.warning(f"⚠️ Could not extract usage from run object: {usage_error}")

            total_tokens = input_tokens + output_tokens + cache_read_tokens
            prompt_tokens = input_tokens + cache_read_tokens  # Total billable prompt including cached
            completion_tokens = output_tokens
            token_source = "ACTUAL (from Gemini API)" if total_tokens > 0 else "ZERO (no run data)"

            if total_tokens == 0:
                # Fallback estimate
                response_chars = len(response_text)
                completion_tokens = max(1, response_chars // 4)
                prompt_tokens = 500
                total_tokens = prompt_tokens + completion_tokens
                token_source = "ESTIMATED (from response length)"

            logger.info(f"📊 Token tracking source: {token_source}")
            logger.info(f"   Prompt tokens: {prompt_tokens}")
            logger.info(f"   Completion tokens: {completion_tokens}")
            logger.info(f"   Cache read tokens: {cache_read_tokens}")
            logger.info(f"   Cache write tokens: {cache_write_tokens}")
            logger.info(f"   Total tokens: {total_tokens}")

            # Use track_gemini_usage_detailed to record cache tokens in request_metadata
            success = await track_gemini_usage_detailed(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                session_id=session_id,
                api_call_type='agent_stream',
                model=model_name
            )

            if success:
                logger.info(f"✅ Tracked {total_tokens} tokens for session {session_id[:8]}... ({token_source})")
            else:
                logger.error(f"❌ Failed to track token usage for session {session_id}")

            # Update chat_messages token_count and chat_sessions aggregates
            # Background task with retry to handle write-through race condition
            import asyncio
            asyncio.create_task(self._update_message_and_session_usage(
                session_id=session_id,
                user_message=user_message,
                response_text=response_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                system_prompt_text=system_prompt_text,
                history_text=history_text,
                tool_def_text=tool_def_text
            ))

        except Exception as e:
            logger.error(f"❌ Error tracking token usage: {e}", exc_info=True)

    async def _update_message_and_session_usage(
        self,
        session_id: str,
        user_message: str,
        response_text: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        system_prompt_text: str = "",
        history_text: str = "",
        tool_def_text: str = ""
    ):
        """Background task: update token counts on the latest user+assistant messages, and session aggregates.

        Columns updated per message:
        - token_count: prompt_tokens for user msg, completion_tokens for bot msg (legacy, full context)
        - message_token_count: tokens for just the message text (via count_tokens API)
        - prompt_token_count: full prompt tokens from run.usage() (on user msg only)
        - completion_token_count: completion tokens from run.usage() (on bot msg only)
        - system_prompt_*: chars/words/tokens for system prompt component
        - history_*: chars/words/tokens for conversation history component
        - tool_def_*: chars/words/tokens for tool definitions component
        - user_msg_*: chars/words/tokens for user message text
        - bot_response_*: chars/words/tokens for bot response text

        Retries up to 3 times with 6s delay to handle write-through flush race condition.
        """
        import asyncio
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        # Compute metrics for both messages
        user_char_count = len(user_message)
        user_word_count = len(user_message.split()) if user_message.strip() else 0
        bot_char_count = len(response_text)
        bot_word_count = len(response_text.split()) if response_text.strip() else 0

        # Compute char/word counts for prompt components
        sp_char = len(system_prompt_text)
        sp_word = len(system_prompt_text.split()) if system_prompt_text.strip() else 0
        hist_char = len(history_text)
        hist_word = len(history_text.split()) if history_text.strip() else 0
        td_char = len(tool_def_text)
        td_word = len(tool_def_text.split()) if tool_def_text.strip() else 0

        # Count tokens for each component via Gemini count_tokens API
        user_message_tokens = 0
        bot_message_tokens = 0
        sp_tokens = 0
        hist_tokens = 0
        td_tokens = 0
        try:
            import os
            from concurrent.futures import ThreadPoolExecutor
            loop = asyncio.get_event_loop()
            token_model = os.getenv("GEMINI_TOKEN_COUNT_MODEL", os.getenv("CHATBOT_MODEL", "gemini-2.5-flash-lite"))

            from ..core.ai import get_genai_client
            genai_client = get_genai_client()
            if genai_client:
                executor = ThreadPoolExecutor(max_workers=4)

                def count_user():
                    return genai_client.models.count_tokens(model=token_model, contents=user_message)

                def count_bot():
                    return genai_client.models.count_tokens(model=token_model, contents=response_text)

                def count_system_prompt():
                    if not system_prompt_text.strip():
                        return None
                    return genai_client.models.count_tokens(model=token_model, contents=system_prompt_text)

                def count_history():
                    if not history_text.strip():
                        return None
                    return genai_client.models.count_tokens(model=token_model, contents=history_text)

                results = await asyncio.gather(
                    loop.run_in_executor(executor, count_user),
                    loop.run_in_executor(executor, count_bot),
                    loop.run_in_executor(executor, count_system_prompt),
                    loop.run_in_executor(executor, count_history),
                )
                user_message_tokens = results[0].total_tokens if results[0] else 0
                bot_message_tokens = results[1].total_tokens if results[1] else 0
                sp_tokens = results[2].total_tokens if results[2] else 0
                hist_tokens = results[3].total_tokens if results[3] else 0

                # Derive tool/overhead tokens from the remainder.
                # When cache is ACTIVE:
                #   cache_read_tokens = sys prompt + tool schema (cached, billed at 90% discount)
                #   input_tokens = history + user msg + multi-turn overhead (non-cached)
                #   Total billable prompt = input_tokens + cache_read_tokens
                # When cache is INACTIVE:
                #   input_tokens = sys prompt + tool schema + history + user msg + multi-turn overhead
                #   cache_read_tokens = 0
                total_prompt = input_tokens + cache_read_tokens
                known_tokens = sp_tokens + hist_tokens + user_message_tokens
                td_tokens = max(0, total_prompt - known_tokens)

                logger.info(f"📊 [MSG_TOKENS] Message token counts: user={user_message_tokens}, bot={bot_message_tokens}")
                logger.info(f"📊 [COMPONENT_TOKENS] system_prompt={sp_tokens}, history={hist_tokens}, tools_overhead={td_tokens}")
                logger.info(f"📊 [DERIVATION] total_prompt={total_prompt} (input={input_tokens} + cache_read={cache_read_tokens}) - known={known_tokens} = tools_overhead={td_tokens}")
        except Exception as tc_err:
            logger.warning(f"⚠️ [MSG_TOKENS] Failed to count message tokens: {tc_err}")

        for attempt in range(3):
            try:
                await asyncio.sleep(6)  # Wait for write-through to flush

                async with get_db_session() as db:
                    # Update the latest user message
                    result = await db.execute(
                        text("""
                            UPDATE chat_messages
                            SET token_count = :token_count,
                                message_token_count = :message_token_count,
                                prompt_token_count = :prompt_token_count,
                                completion_token_count = 0,
                                system_prompt_char_count = :sp_char,
                                system_prompt_word_count = :sp_word,
                                system_prompt_token_count = :sp_tokens,
                                history_char_count = :hist_char,
                                history_word_count = :hist_word,
                                history_token_count = :hist_tokens,
                                tool_def_char_count = :td_char,
                                tool_def_word_count = :td_word,
                                tool_def_token_count = :td_tokens,
                                user_msg_char_count = :user_msg_char,
                                user_msg_word_count = :user_msg_word,
                                user_msg_token_count = :user_msg_tokens,
                                system_prompt_text = :sp_text,
                                history_text = :hist_text,
                                tool_def_text = :td_text,
                                updated_at = NOW()
                            WHERE id = (
                                SELECT id FROM chat_messages
                                WHERE session_id = CAST(:session_id AS UUID) AND role = 'user'
                                ORDER BY created_at DESC LIMIT 1
                            )
                        """),
                        {
                            "session_id": session_id,
                            "token_count": input_tokens + cache_read_tokens,
                            "message_token_count": user_message_tokens,
                            "prompt_token_count": input_tokens + cache_read_tokens,
                            "sp_char": sp_char,
                            "sp_word": sp_word,
                            "sp_tokens": sp_tokens,
                            "hist_char": hist_char,
                            "hist_word": hist_word,
                            "hist_tokens": hist_tokens,
                            "td_char": td_char,
                            "td_word": td_word,
                            "td_tokens": td_tokens,
                            "user_msg_char": user_char_count,
                            "user_msg_word": user_word_count,
                            "user_msg_tokens": user_message_tokens,
                            "sp_text": system_prompt_text,
                            "hist_text": history_text,
                            "td_text": tool_def_text,
                        }
                    )
                    user_updated = result.rowcount > 0

                    # Update the latest assistant message
                    result = await db.execute(
                        text("""
                            UPDATE chat_messages
                            SET token_count = :token_count,
                                message_token_count = :message_token_count,
                                prompt_token_count = 0,
                                completion_token_count = :completion_token_count,
                                bot_response_char_count = :bot_char,
                                bot_response_word_count = :bot_word,
                                bot_response_token_count = :bot_tokens,
                                updated_at = NOW()
                            WHERE id = (
                                SELECT id FROM chat_messages
                                WHERE session_id = CAST(:session_id AS UUID) AND role = 'assistant'
                                ORDER BY created_at DESC LIMIT 1
                            )
                        """),
                        {
                            "session_id": session_id,
                            "token_count": output_tokens,
                            "message_token_count": bot_message_tokens,
                            "completion_token_count": output_tokens,
                            "bot_char": bot_char_count,
                            "bot_word": bot_word_count,
                            "bot_tokens": bot_message_tokens,
                        }
                    )
                    bot_updated = result.rowcount > 0

                    # Update session aggregates (add this turn's metrics)
                    total_char = user_char_count + bot_char_count
                    total_word = user_word_count + bot_word_count
                    total_prompt_with_cache = input_tokens + cache_read_tokens
                    total_token = total_prompt_with_cache + output_tokens
                    total_msg_tokens = user_message_tokens + bot_message_tokens

                    await db.execute(
                        text("""
                            UPDATE chat_sessions
                            SET total_character_count = total_character_count + :chars,
                                total_word_count = total_word_count + :words,
                                total_token_count = total_token_count + :tokens,
                                total_message_token_count = total_message_token_count + :msg_tokens,
                                total_prompt_token_count = total_prompt_token_count + :prompt_tokens,
                                total_completion_token_count = total_completion_token_count + :completion_tokens,
                                total_system_prompt_token_count = total_system_prompt_token_count + :sp_tok,
                                total_history_token_count = total_history_token_count + :hist_tok,
                                total_tool_def_token_count = total_tool_def_token_count + :td_tok,
                                total_user_msg_token_count = total_user_msg_token_count + :user_msg_tok,
                                total_bot_response_token_count = total_bot_response_token_count + :bot_resp_tok,
                                updated_at = NOW()
                            WHERE id = CAST(:session_id AS UUID)
                        """),
                        {
                            "session_id": session_id,
                            "chars": total_char,
                            "words": total_word,
                            "tokens": total_token,
                            "msg_tokens": total_msg_tokens,
                            "prompt_tokens": total_prompt_with_cache,
                            "completion_tokens": output_tokens,
                            "sp_tok": sp_tokens,
                            "hist_tok": hist_tokens,
                            "td_tok": td_tokens,
                            "user_msg_tok": user_message_tokens,
                            "bot_resp_tok": bot_message_tokens,
                        }
                    )

                    await db.commit()

                    logger.info(f"✅ [USAGE_UPDATE] Updated message & session usage for {session_id[:8]}...")
                    logger.info(f"   User msg: {user_char_count} chars, {user_word_count} words, msg_tokens={user_message_tokens}, prompt_tokens={input_tokens} (updated={user_updated})")
                    logger.info(f"   Bot msg: {bot_char_count} chars, {bot_word_count} words, msg_tokens={bot_message_tokens}, completion_tokens={output_tokens} (updated={bot_updated})")
                    logger.info(f"   Components: sys_prompt={sp_tokens}t/{sp_char}c/{sp_word}w, history={hist_tokens}t/{hist_char}c/{hist_word}w, tools={td_tokens}t/{td_char}c/{td_word}w")
                    logger.info(f"   Session totals += {total_char} chars, {total_word} words, {total_token} tokens, {total_msg_tokens} msg_tokens")
                    return

            except Exception as e:
                logger.warning(f"⚠️ [USAGE_UPDATE] Attempt {attempt + 1}/3 failed for {session_id[:8]}...: {e}")

        logger.error(f"❌ [USAGE_UPDATE] All 3 attempts failed for {session_id[:8]}...")

    async def _save_agent_run_steps(self, session_id: str, run):
        """Save per-step breakdown of the agent run to agent_run_steps table.

        Iterates run.all_messages() and records each part (system prompt, user prompt,
        text response, tool call, tool return, thinking) as a separate row with
        char/word/token counts.
        """
        import asyncio
        await asyncio.sleep(8)  # Wait for write-through + message update to finish

        try:
            all_messages = run.all_messages()
            if not all_messages:
                return

            from shared.sqlalchemy_db import get_db_session
            from sqlalchemy import text
            import os
            from concurrent.futures import ThreadPoolExecutor
            from ..core.ai import get_genai_client

            # Get user_message_id (latest user message in this session)
            user_message_id = None
            async with get_db_session() as db:
                result = await db.execute(
                    text("""
                        SELECT id FROM chat_messages
                        WHERE session_id = CAST(:sid AS UUID) AND role = 'user'
                        ORDER BY created_at DESC LIMIT 1
                    """),
                    {"sid": session_id}
                )
                row = result.fetchone()
                if row:
                    user_message_id = str(row[0])

            # Collect steps from all_messages
            steps = []
            step_num = 0
            for msg in all_messages:
                msg_type = type(msg).__name__  # ModelRequest or ModelResponse
                step_type = 'model_request' if msg_type == 'ModelRequest' else 'model_response'

                for part in getattr(msg, 'parts', []):
                    step_num += 1
                    part_type_name = type(part).__name__
                    content = ''
                    tool_name = None

                    if part_type_name == 'SystemPromptPart':
                        part_label = 'system_prompt'
                        content = getattr(part, 'content', '') or ''
                    elif part_type_name == 'UserPromptPart':
                        part_label = 'user_prompt'
                        content = str(getattr(part, 'content', '') or '')
                    elif part_type_name == 'TextPart':
                        part_label = 'text'
                        content = getattr(part, 'content', '') or ''
                    elif part_type_name == 'ThinkingPart':
                        part_label = 'thinking'
                        content = getattr(part, 'content', '') or ''
                    elif part_type_name in ('ToolCallPart', 'BuiltinToolCallPart'):
                        part_label = 'tool_call'
                        tool_name = getattr(part, 'tool_name', 'unknown')
                        args = getattr(part, 'args', None)
                        content = f"Tool: {tool_name}\nArgs: {str(args)[:500]}" if args else f"Tool: {tool_name}"
                    elif part_type_name in ('ToolReturnPart', 'BuiltinToolReturnPart'):
                        part_label = 'tool_return'
                        tool_name = getattr(part, 'tool_name', 'unknown')
                        ret_content = getattr(part, 'content', '')
                        content = str(ret_content)[:5000] if ret_content else ''
                    else:
                        part_label = part_type_name.lower()
                        content = str(getattr(part, 'content', '') or '')

                    content_str = str(content)
                    steps.append({
                        'step_number': step_num,
                        'step_type': step_type,
                        'part_type': part_label,
                        'tool_name': tool_name,
                        'content_preview': content_str[:1000],
                        'char_count': len(content_str),
                        'word_count': len(content_str.split()) if content_str.strip() else 0,
                        'full_content': content_str,  # for token counting
                    })

            if not steps:
                return

            # Count tokens for each step in parallel
            genai_client = get_genai_client()
            token_model = os.getenv("GEMINI_TOKEN_COUNT_MODEL", os.getenv("CHATBOT_MODEL", "gemini-2.5-flash-lite"))
            if genai_client:
                loop = asyncio.get_event_loop()
                executor = ThreadPoolExecutor(max_workers=min(len(steps), 8))

                async def count_step_tokens(text_content):
                    if not text_content.strip():
                        return 0
                    try:
                        result = await loop.run_in_executor(
                            executor,
                            lambda: genai_client.models.count_tokens(model=token_model, contents=text_content)
                        )
                        return result.total_tokens if result else 0
                    except Exception:
                        return 0

                token_results = await asyncio.gather(
                    *[count_step_tokens(s['full_content']) for s in steps]
                )
                for i, tok in enumerate(token_results):
                    steps[i]['token_count'] = tok

            # Insert all steps
            async with get_db_session() as db:
                for s in steps:
                    await db.execute(
                        text("""
                            INSERT INTO agent_run_steps
                                (session_id, user_message_id, step_number, step_type, part_type,
                                 tool_name, content_preview, char_count, word_count, token_count)
                            VALUES
                                (CAST(:sid AS UUID), CAST(:mid AS UUID), :step, :stype, :ptype,
                                 :tool, :preview, :chars, :words, :tokens)
                        """),
                        {
                            "sid": session_id,
                            "mid": user_message_id,
                            "step": s['step_number'],
                            "stype": s['step_type'],
                            "ptype": s['part_type'],
                            "tool": s.get('tool_name'),
                            "preview": s['content_preview'],
                            "chars": s['char_count'],
                            "words": s['word_count'],
                            "tokens": s.get('token_count', 0),
                        }
                    )
                await db.commit()

            logger.info(f"✅ [RUN_STEPS] Saved {len(steps)} agent run steps for session {session_id[:8]}...")
            for s in steps:
                logger.info(f"   Step {s['step_number']}: {s['step_type']}/{s['part_type']} - {s.get('token_count',0)} tokens, {s['char_count']} chars")

        except Exception as e:
            logger.warning(f"⚠️ [RUN_STEPS] Failed to save agent run steps: {e}")

# Global streaming service instance
streaming_service = StreamingService()
