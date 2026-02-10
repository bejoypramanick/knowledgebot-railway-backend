import time
import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List

from google.genai import types
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from chatbot_orchestration.dao.chat_dao import ChatDAO
from shared.otel_logger import get_otel_logger

from ..core.ai import MODEL_NAME, get_genai_client
from ..core.dependencies import ChatSessionDeps

logger = get_otel_logger("agent_service", "chatbot-orchestration")

class PydanticAIGatewayService:
    """ Service class for Pydantic AI integration with Gemini FileSearch """
    
    def __init__(self):
        self.genai_client = None
        self.chat_dao = ChatDAO()  # Unified ChatDAO for all chat operations
        
    async def initialize(self):
        if not self.genai_client:
            self.genai_client = get_genai_client()
    
    async def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        logger.info(f"🔍 Retrieving session metadata for session: {session_id}")

        try:
            session_data = await self.chat_dao.get_session_metadata(session_id)

            if not session_data:
                return {'session_id': session_id, 'is_new_session': True}

            return {
                'session_id': session_id,
                'file_search_store_id': session_data.get('file_search_store_id'),
                'cached_content_id': session_data.get('cached_content_id'),
                'is_new_session': False
            }
        except Exception as e:
            logger.error(f"❌ Error retrieving session metadata: {e}")
            return {'session_id': session_id, 'is_new_session': True}

    async def get_or_create_file_search_store(self, session_id: str) -> str:
        if not self.genai_client:
            raise ValueError("GenAI client not initialized")

        try:
            import os

            # Get store display name from environment variable
            store_display_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

            if hasattr(self.genai_client, 'stores'):
                stores = list(self.genai_client.stores.list())
                app_store = None
                for store in stores:
                    if hasattr(store, 'display_name') and store_display_name.lower().replace('-', '_') in store.display_name.lower().replace('-', '_'):
                        app_store = store
                        break

                if app_store:
                    return app_store.name
                else:
                    # Create new store using correct Python client API with name from env
                    new_store = self.genai_client.stores.create(
                        displayName=store_display_name.replace('-', ' ').title()
                    )
                    logger.info(f"Created FileSearch store: {new_store.name}")
                    return new_store.name
            else:
                return f"knowledgebot_store_{session_id[:8]}"
        except Exception as e:
            logger.error(f"❌ Error managing FileSearchStore: {e}")
            return f"knowledgebot_store_{session_id[:8]}"

    async def get_or_create_cached_content(self, system_prompt: str) -> str:
        """
        Create cached content for system prompt.

        IMPORTANT: Gemini requires minimum 2,048 tokens for caching.
        Our system prompt is ~32,768 tokens, which is well above the minimum.
        """
        if not self.genai_client:
            raise ValueError("GenAI client not initialized")

        try:
            if not hasattr(self.genai_client, 'caches'):
                logger.warning("⚠️ Gemini caches API not available")
                return f"no_cache_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

            # Estimate token count (rough approximation: ~4 chars per token)
            estimated_tokens = len(system_prompt) / 4
            logger.info(f"📊 System prompt size: {len(system_prompt)} chars (~{int(estimated_tokens)} tokens)")

            if estimated_tokens < 2048:
                logger.warning(f"⚠️ System prompt too small for caching (< 2,048 tokens). Size: {int(estimated_tokens)} tokens")
                return f"no_cache_too_small_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

            cached_content = self.genai_client.caches.create(
                model=MODEL_NAME,
                config=types.CreateCachedContentConfig(
                    display_name=f"system_prompt_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                    system_instruction=types.Content(parts=[types.Part(text=system_prompt)]),
                    ttl="3600s"  # 1 hour cache
                )
            )
            logger.info(f"✅ Created cached content with 1 hour TTL: {cached_content.name}")
            logger.info(f"📝 Cache contains ~{int(estimated_tokens)} tokens (minimum 2,048 required)")
            return cached_content.name
        except Exception as e:
            logger.error(f"❌ Error creating cached content: {e}")
            raise

    async def get_cached_content_id(self, session_id: str) -> str:
        session_metadata = await self.get_session_metadata(session_id)
        return session_metadata.get('cached_content_id')

    async def run_agent_with_fallback(self, agent: Agent, user_message: str, session_deps: ChatSessionDeps) -> Any:
        """Run agent with proper error handling for cache expiration and fallback."""
        try:
            logger.info("Running agent with cached content")
            result = await agent.run(user_message, deps=session_deps)
            logger.info("Agent run completed successfully")
            return result
        except Exception as e:
            logger.error(f"Agent run failed with cached content: {e}")
            
            # Check if it's a cache-related error
            if "cached_content" in str(e).lower() or "cache" in str(e).lower():
                logger.warning("Cache error detected, falling back to no cache")
                
                # Create fallback agent without cache
                try:
                    fallback_model = GoogleModel(MODEL_NAME)
                    fallback_agent = Agent(
                        fallback_model,
                        system_prompt=agent.system_prompt,
                        tools=agent.tools,
                        deps_type=ChatSessionDeps,
                    )
                    
                    logger.info("Running fallback agent without cache")
                    result = await fallback_agent.run(user_message, deps=session_deps)
                    logger.info("Fallback agent run completed successfully")
                    return result
                    
                except Exception as fallback_error:
                    logger.error(f"Fallback agent also failed: {fallback_error}")
                    raise fallback_error
            else:
                # Non-cache related error, re-raise
                raise e

    async def _fetch_persona_config(self) -> Dict[str, Any]:
        """Fetch active persona and response policy from configuration service."""
        try:
            import os
            import httpx

            config_url = os.getenv("CONFIGURATION_SERVICE_URL", "https://api-gateway-common.up.railway.app/api/v1/gateway/configuration/chatAgentConfig")

            headers = {}
            api_key = os.getenv("INTERNAL_API_KEY")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient(timeout=10.0, headers=headers) as http_client:
                response = await http_client.get(config_url)
                if response.status_code == 200:
                    config_data = response.json()
                    persona_data = config_data.get("persona", {})
                    security_data = config_data.get("security", {})

                    return {
                        "persona_prompt": persona_data.get("system_prompt", ""),
                        "persona_name": persona_data.get("selected_persona", "KnowledgeBot"),
                        "response_policy": config_data.get("response_policy", ""),
                        "response_timeout": security_data.get("response_timeout", 30)
                    }
                else:
                    logger.warning(f"⚠️ Failed to fetch persona config: {response.status_code}")
                    return self._get_default_persona_config()
        except Exception as e:
            logger.error(f"❌ Error fetching persona config: {e}")
            return self._get_default_persona_config()

    def _get_default_persona_config(self) -> Dict[str, Any]:
        """Return default persona configuration."""
        return {
            "persona_prompt": "",
            "persona_name": "KnowledgeBot",
            "response_policy": "Be helpful, accurate, and concise in your responses.",
            "response_timeout": 30
        }

    async def _build_system_prompt(self, persona_config: Dict[str, Any]) -> str:
        """Build comprehensive system prompt using the long detailed prompt with persona and response policy."""
        from ..agent.prompt import get_system_prompt

        persona_name = persona_config.get("persona_name", "KnowledgeBot")
        persona_prompt = persona_config.get("persona_prompt", "")
        response_policy_text = persona_config.get("response_policy", "")

        # Build custom prompt section with persona information
        custom_prompt = f"""## ACTIVE PERSONA: {persona_name}

{persona_prompt if persona_prompt else "You are a helpful AI assistant with expertise in information retrieval and data analysis."}

## ACTIVE RESPONSE POLICY:
{response_policy_text if response_policy_text else "Be helpful, accurate, and concise in your responses."}

## PERSONA-SPECIFIC INSTRUCTIONS:
- Maintain the personality and tone of {persona_name}
- Follow the response policy strictly
- Use the persona's knowledge domain and expertise
- Adapt communication style to match the persona's characteristics
"""

        # Convert response_policy_text to numeric value for get_system_prompt
        # Balanced policy (50) as default, can be adjusted based on response_policy_text content
        response_policy_value = 50  # Balanced by default

        if response_policy_text:
            lower_policy = response_policy_text.lower()
            if any(word in lower_policy for word in ['strict', 'only', 'must', 'always']):
                response_policy_value = 80  # Strict
            elif any(word in lower_policy for word in ['flexible', 'creative', 'may']):
                response_policy_value = 30  # Flexible

        # Get the comprehensive system prompt with persona integration
        system_prompt = get_system_prompt(
            custom_prompt=custom_prompt,
            response_policy=response_policy_value
        )

        logger.info(f"📝 Built comprehensive system prompt with persona: {persona_name}")
        logger.info(f"📊 Response policy value: {response_policy_value}")

        return system_prompt

    async def create_agent(self, session_id: str, tools: List[Any], user_email: str = None) -> Agent:
        """Create an agent instance with proper Pydantic AI settings, dynamic persona, and caching."""
        logger.info(f"Creating agent for session {session_id}")

        try:
            # FIX #2: Initialize GenAI client - FAIL FAST if critical
            await self.initialize()
            if not self.genai_client:
                raise RuntimeError("GenAI client failed to initialize - cannot create agent")

            # FIX #1: Run independent operations in parallel
            logger.info("🔄 Fetching persona config and session metadata in parallel...")
            persona_config, cached_content_id = await asyncio.gather(
                self._fetch_persona_config(),
                self.get_cached_content_id(session_id),
                return_exceptions=False  # Fail fast if any critical operation fails
            )

            logger.info(f"🎭 Using persona: {persona_config['persona_name']}")

            # Build system prompt (depends on persona_config, so must be sequential)
            system_prompt = await self._build_system_prompt(persona_config)
            logger.info(f"📝 System prompt: {len(system_prompt)} characters")

            # FIX #4: Better cache validation - check for valid cache ID and verify it exists
            newly_created_cache = False
            if not cached_content_id or cached_content_id.startswith('no_cache_'):
                # No valid cache exists, create new one
                try:
                    logger.info("📝 Creating new cached content...")
                    cached_content_id = await self.get_or_create_cached_content(system_prompt)
                    newly_created_cache = True
                    logger.info(f"✅ Created new cached content: {cached_content_id}")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to create cached content: {e}")
                    cached_content_id = None
            else:
                # Validate existing cache - check if it's still valid (not expired)
                try:
                    logger.info(f"♻️ Validating existing cached content: {cached_content_id}")
                    cache_info = self.genai_client.caches.get(cached_content_id)

                    if hasattr(cache_info, 'expire_time'):
                        expire_time = cache_info.expire_time
                        if isinstance(expire_time, str):
                            from dateutil import parser
                            expire_time = parser.parse(expire_time)

                        if expire_time < datetime.now(expire_time.tzinfo):
                            logger.warning(f"⚠️ Cached content expired, creating new cache")
                            cached_content_id = await self.get_or_create_cached_content(system_prompt)
                            newly_created_cache = True
                        else:
                            logger.info(f"✅ Cache is valid, expires at: {expire_time}")
                    else:
                        logger.info(f"✅ Reusing existing cached content: {cached_content_id}")

                except Exception as e:
                    logger.warning(f"⚠️ Failed to validate cache (might be expired), creating new one: {e}")
                    try:
                        cached_content_id = await self.get_or_create_cached_content(system_prompt)
                        newly_created_cache = True
                    except Exception as create_error:
                        logger.error(f"❌ Failed to create new cache: {create_error}")
                        cached_content_id = None

            # FIX #3: Removed file_search_store_id fetching
            # File search store is managed by the search_knowledge_base tool, not the Agent
            # The tool uses environment variable GEMINI_FILE_SEARCH_STORE_NAME directly

            # CACHING TEMPORARILY DISABLED: Pydantic AI v1.48.0 doesn't support google_cached_content parameter
            # TODO: Investigate proper caching mechanism for this Pydantic AI version
            use_cache = False  # bool(cached_content_id and not cached_content_id.startswith('no_cache_'))

            if use_cache:
                # Use cached content - system prompt is in the cache
                logger.info(f"🚀 Using cached content: {cached_content_id}")

                # Pass google_cached_content directly to GoogleModel
                # This is a provider-specific parameter for Gemini's explicit caching
                google_model = GoogleModel(
                    MODEL_NAME,
                    google_cached_content=cached_content_id  # Pydantic AI standard parameter
                )

                # IMPORTANT: Don't pass system_prompt when using cached content
                # The cache is an immutable prefix - system prompt is already in the cache
                agent = Agent(
                    google_model,
                    system_prompt=None,  # Already in cached content (immutable prefix)
                    tools=tools,  # Tools can be passed separately
                    deps_type=ChatSessionDeps,
                )
                logger.info("✅ Agent created with CACHED system prompt (explicit caching enabled)")
            else:
                # No cache available - use full system prompt
                logger.info("📝 No cache available - using full system prompt")
                google_model = GoogleModel(MODEL_NAME)

                agent = Agent(
                    google_model,
                    system_prompt=system_prompt,
                    tools=tools,
                    deps_type=ChatSessionDeps,
                )
                logger.info("✅ Agent created with full system prompt (caching disabled for this session)")

            # Save cached_content_id to DB if we created one (for future use when caching is re-enabled)
            if newly_created_cache and cached_content_id:
                # Run DB update in background - don't block agent creation
                asyncio.create_task(
                    self._save_cache_to_session_background(session_id, cached_content_id)
                )

            return agent

        except Exception as e:
            logger.error(f"Error creating agent: {e}")
            raise e

    async def stream_agent_response(self, message: str, session_id: str, tools: List[Any]):
        """Stream agent response using Pydantic AI with RAG, token tracking, and proper error handling."""
        try:
            logger.info(f"🚀 Starting agent stream for session: {session_id}")
            logger.info(f"📝 Message: {message[:100]}...")

            # Create agent with dynamic persona and tools
            agent = await self.create_agent(session_id, tools)

            # Create session dependencies
            session_deps = ChatSessionDeps(session_id=session_id)

            # Get chat history for context
            chat_history = await self.get_chat_history(session_id)
            history_count = len(chat_history.get('messages', []))
            logger.info(f"📚 Retrieved {history_count} messages from chat history")

            # Format chat history context if available
            history_context = ""
            if chat_history and chat_history.get("messages"):
                history_context = "\n\nRECENT CONVERSATION HISTORY:\n"
                for msg in chat_history["messages"][-3:]:  # Last 3 messages for context
                    if msg.get("sender") == "user":
                        history_context += f"User: {msg.get('message', '')}\n"
                    elif msg.get("sender") in ["agent", "bot"]:
                        history_context += f"Assistant: {msg.get('message', '')}\n"

            # Construct user message with history context
            user_message_with_context = f"{message}{history_context}"

            logger.info(f"🤖 Running agent stream...")

            # Use Pydantic AI's run_stream for streaming responses
            full_response_text = ""
            async with agent.run_stream(user_message_with_context, deps=session_deps) as result:
                # Stream chunks as they arrive
                async for chunk in result.stream_text(delta=True):
                    full_response_text += chunk
                    # Format as JSON for frontend compatibility
                    chunk_data = {
                        "type": "chunk",
                        "content": chunk
                    }
                    yield f"{json.dumps(chunk_data)}\n\n"

                logger.info(f"✅ Stream completed - Total response: {len(full_response_text)} chars")

                # Track token usage after stream completes
                try:
                    # Access the underlying response for token tracking
                    if hasattr(result, 'usage'):
                        await self._track_token_usage_from_result(result, session_id)
                    else:
                        logger.warning("⚠️ No usage data available from agent result")
                except Exception as token_error:
                    logger.error(f"❌ Error tracking tokens: {token_error}")

                # Send completion signal
                complete_data = {
                    "type": "complete",
                    "content": full_response_text,
                    "sources": []
                }
                yield f"{json.dumps(complete_data)}\n\n"

        except Exception as e:
            logger.error(f"❌ Error in agent stream: {e}")
            error_data = {
                "type": "error",
                "content": f"I encountered an error while processing your message: {str(e)}"
            }
            yield f"{json.dumps(error_data)}\n\n"

    async def _track_token_usage_from_result(self, result: Any, session_id: str):
        """Track token usage from Pydantic AI result."""
        try:
            from ..dao.token_dao import TokenDAO
            import uuid
            import os

            token_dao = TokenDAO()
            message_id = str(uuid.uuid4())

            # Extract token counts from Pydantic AI result
            usage = result.usage() if callable(result.usage) else result.usage

            prompt_tokens = getattr(usage, 'request_tokens', 0) or getattr(usage, 'prompt_tokens', 0)
            completion_tokens = getattr(usage, 'response_tokens', 0) or getattr(usage, 'completion_tokens', 0)
            total_tokens = getattr(usage, 'total_tokens', 0) or (prompt_tokens + completion_tokens)

            model_name = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash-lite")

            success = await token_dao.save_token_usage(
                session_id=session_id,
                message_id=message_id,
                provider='gemini',
                model=model_name,
                prompt_tokens=int(prompt_tokens),
                completion_tokens=int(completion_tokens),
                total_tokens=int(total_tokens),
                api_call_type='agent_stream'
            )

            if success:
                logger.info(f"✅ Tracked {total_tokens} tokens for session {session_id}")
            else:
                logger.error(f"❌ Failed to track token usage")

        except Exception as e:
            logger.error(f"Error tracking token usage from result: {e}")

    async def _save_cache_to_session_background(self, session_id: str, cached_content_id: str):
        """Background task to save cached_content_id to database"""
        try:
            await self.chat_dao.update_session_cache_info(
                session_id=session_id,
                cached_content_id=cached_content_id
            )
            logger.info(f"✅ Background: Saved cached_content_id to session {session_id}")
        except Exception as e:
            logger.warning(f"⚠️ Background: Failed to save cached_content_id: {e}")

    async def update_session_metadata(self, session_id: str, file_search_store_id: str = None, cached_content_id: str = None):
        """Update session metadata in database with file_search_store_id and cached_content_id"""
        try:
            if not self.chat_dao:
                logger.warning("⚠️ ChatDAO not available, skipping session metadata update")
                return

            # Use chat_dao to update session metadata
            await self.chat_dao.update_session_cache_info(
                session_id=session_id,
                cached_content_id=cached_content_id
            )
            logger.info(f"✅ Updated session {session_id} with cached_content_id: {cached_content_id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update session metadata: {e}")

    async def process_message(self, message: str, session_id: str) -> str:
        """Process a chat message and return response"""
        try:
            # This would need to be implemented based on actual chat logic
            # For now, return a simple response
            return f"Response to: {message}"
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise

    async def get_chat_history(self, session_id: str) -> Dict[str, Any]:
        """Get chat history for a session"""
        try:
            # Use ChatDAO to get chat history
            history = await self.chat_dao.get_chat_history(session_id)
            return history or {"messages": []}
        except Exception as e:
            logger.error(f"❌ Error getting chat history: {e}")
            return {"messages": []}


    async def get_available_agents(self) -> list:
        """Get list of available agents"""
        try:
            # This would need to be implemented based on actual agent logic
            # For now, return empty list
            return []
        except Exception as e:
            logger.error(f"Error getting available agents: {e}")
            raise

    async def get_agent_info(self, agent_id: str) -> dict:
        """Get information about a specific agent"""
        try:
            # This would need to be implemented based on actual agent logic
            # For now, return empty dict
            return {}
        except Exception as e:
            logger.error(f"Error getting agent info: {e}")
            raise

pydantic_ai_service = PydanticAIGatewayService()

class SessionStateManager:
    """Manages session state for multi-turn conversational loops."""
    def __init__(self):
        self.session_states = {}

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        return self.session_states.get(session_id, {
            'session_id': session_id,
            'turn_count': 0,
            'message_history': [],
            'last_activity': time.time()
        })
    
    def update_session_state(self, session_id: str, result: Any) -> Dict[str, Any]:
        state = self.get_session_state(session_id)
        state['turn_count'] += 1
        if hasattr(result, 'all_messages'):
            state['message_history'] = result.all_messages()
        state['last_activity'] = time.time()
        self.session_states[session_id] = state
        return state

session_state_manager = SessionStateManager()
