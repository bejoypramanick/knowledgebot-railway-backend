import time
import json
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List

from google.genai import types
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
from pydantic_ai.usage import Usage

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

    async def get_or_create_cached_content(self, system_prompt: str, tools: List[Any] = None) -> str:
        """
        Create cached content for system prompt and tools.

        IMPORTANT:
        - Gemini requires minimum 2,048 tokens for caching
        - Our system prompt is ~32,768 tokens, which is well above the minimum
        - Per Gemini API: "CachedContent can not be used with GenerateContent request setting
          system_instruction, tools or tool_config."
        - Solution: Include tools IN the cached content, not in GenerateContent request
        - This enables both caching benefits AND tool usage together

        Args:
            system_prompt: The system instruction text to cache
            tools: Optional list of Pydantic AI tools to include in cache

        Returns:
            Cached content ID or "no_cache_*" identifier
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

            # Prepare cache configuration
            cache_config = types.CreateCachedContentConfig(
                display_name=f"system_prompt_tools_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                system_instruction=types.Content(parts=[types.Part(text=system_prompt)]),
                ttl="3600s"  # 1 hour cache
            )

            # Include tools in cached content if provided
            # This is REQUIRED by Gemini API - tools cannot be passed separately when using cache
            if tools and len(tools) > 0:
                logger.info(f"📦 Converting and including {len(tools)} tools in cached content")
                try:
                    from ..tools.converters import convert_tools_to_gemini_format
                    gemini_tools = convert_tools_to_gemini_format(tools)

                    if gemini_tools:
                        cache_config.tools = gemini_tools
                        logger.info(f"✅ Added {len(tools)} tools to cache configuration")
                    else:
                        logger.warning(f"⚠️ No tools converted successfully - cache will have no tools")

                except Exception as tool_error:
                    logger.error(f"❌ Failed to convert tools for caching: {tool_error}")
                    import traceback
                    logger.error(f"❌ Traceback: {traceback.format_exc()}")
                    # Decide: fail fast or continue without tools?
                    # For now, fail fast to ensure tools work correctly
                    raise RuntimeError(f"Cannot create cache with tools: {tool_error}") from tool_error

            cached_content = self.genai_client.caches.create(
                model=MODEL_NAME,
                config=cache_config
            )

            tool_status = f" with {len(tools)} tools" if tools else " (no tools)"
            logger.info(f"✅ Created cached content{tool_status} - TTL: 1 hour - ID: {cached_content.name}")
            logger.info(f"📝 Cache contains ~{int(estimated_tokens)} tokens (minimum 2,048 required)")
            return cached_content.name

        except Exception as e:
            logger.error(f"❌ Error creating cached content: {e}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
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

    async def create_agent(self, session_id: str, system_prompt: str = "", tools: List[Any] = None, user_email: str = "anonymous@example.com") -> Agent:
        """Create an agent instance with proper Pydantic AI settings, dynamic persona, and caching."""
        logger.info("="*80)
        logger.info(f"🚀 CREATE_AGENT STARTED - Session: {session_id}")
        logger.info("="*80)

        logger.info(f"📋 Input Parameters:")
        logger.info(f"  - session_id: {session_id}")
        logger.info(f"  - user_email: {user_email}")
        logger.info(f"  - system_prompt length: {len(system_prompt) if system_prompt else 0}")
        logger.info(f"  - tools parameter type: {type(tools)}")

        if tools is not None:
            logger.info(f"  - tools count: {len(tools)}")
            for i, tool in enumerate(tools):
                tool_name = getattr(tool, '__name__', str(tool))
                logger.info(f"    Tool [{i}]: {tool_name} (type: {type(tool).__name__})")
        else:
            logger.info(f"  - tools: None")

        # FIX: Ensure tools is a valid list without None values to prevent 'NoneType object is not iterable' errors
        logger.info(f"\n🔧 STEP 1: Validating and processing tools list")
        if tools is None:
            tools = []
            logger.info("  ✓ Tools was None, initialized to empty list")
        else:
            # Filter out any None values from the tools list
            original_count = len(tools)
            tools = [tool for tool in tools if tool is not None]
            filtered_count = len(tools)
            if original_count != filtered_count:
                logger.warning(f"  ⚠️ Filtered out {original_count - filtered_count} None tools from tools list")
                logger.info(f"  ✓ Final tools count: {filtered_count} valid tools")
            else:
                logger.info(f"  ✓ All {filtered_count} tools are valid (no None values)")

        logger.info(f"  ✓ Final tools: {[getattr(t, '__name__', str(t)) for t in tools]}")

        try:
            # FIX #2: Initialize GenAI client - FAIL FAST if critical
            logger.info(f"\n🔧 STEP 2: Initializing GenAI client")
            await self.initialize()
            if not self.genai_client:
                logger.error("  ❌ GenAI client initialization failed!")
                raise RuntimeError("GenAI client failed to initialize - cannot create agent")
            logger.info("  ✓ GenAI client initialized successfully")

            # FIX #1: Run independent operations in parallel
            logger.info(f"\n🔧 STEP 3: Fetching persona config and cached content ID")
            try:
                persona_config, cached_content_id = await asyncio.gather(
                    self._fetch_persona_config(),
                    self.get_cached_content_id(session_id),
                    return_exceptions=False  # Fail fast if any critical operation fails
                )
                logger.info(f"  ✓ Persona config retrieved: {persona_config['persona_name']}")
                logger.info(f"  ✓ Cached content ID: {cached_content_id if cached_content_id else 'None (will create new)'}")
            except Exception as fetch_error:
                logger.error(f"  ❌ Failed to fetch persona/cache: {fetch_error}")
                raise

            # Build system prompt (depends on persona_config, so must be sequential)
            logger.info(f"\n🔧 STEP 4: Building system prompt")
            try:
                system_prompt = await self._build_system_prompt(persona_config)
                logger.info(f"  ✓ System prompt built: {len(system_prompt)} characters")
                logger.info(f"  ✓ Estimated tokens: ~{int(len(system_prompt) / 4)}")
            except Exception as prompt_error:
                logger.error(f"  ❌ Failed to build system prompt: {prompt_error}")
                raise

            # FIX #4: Better cache validation - check for valid cache ID and verify it exists
            logger.info(f"\n🔧 STEP 5: Cache validation and management")
            newly_created_cache = False

            # IMPORTANT: Invalidate old caches that don't include tools
            # Old caches were created without tools, so force recreation if tools are present
            if cached_content_id and tools and len(tools) > 0:
                logger.warning(f"⚠️ Invalidating existing cache - tools were recently added to cache format")
                logger.warning(f"⚠️ Cache {cached_content_id} may not include tools, forcing recreation")
                cached_content_id = None  # Force cache recreation with tools

            if not cached_content_id or cached_content_id.startswith('no_cache_'):
                # No valid cache exists, create new one
                tool_count = len(tools) if tools else 0
                logger.info(f"  → No valid cache found, creating new cached content with {tool_count} tools")
                if tools:
                    logger.info(f"  → Tools to be cached:")
                    for idx, tool in enumerate(tools, 1):
                        tool_name = getattr(tool, '__name__', str(tool))
                        logger.info(f"     {idx}. {tool_name}")
                try:
                    # Pass tools to cache creation - they must be included in cached content
                    cached_content_id = await self.get_or_create_cached_content(system_prompt, tools)
                    newly_created_cache = True
                    logger.info(f"  ✓ Created new cached content: {cached_content_id}")
                    if tools:
                        logger.info(f"  ✓ Cache includes {len(tools)} tools")
                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to create cached content: {e}")
                    logger.warning(f"  → Will proceed without caching")
                    cached_content_id = None
            else:
                # Validate existing cache - check if it's still valid (not expired)
                logger.info(f"  → Validating existing cache: {cached_content_id}")
                try:
                    cache_info = self.genai_client.caches.get(cached_content_id)
                    logger.info(f"  ✓ Cache found, checking expiration")

                    if hasattr(cache_info, 'expire_time'):
                        expire_time = cache_info.expire_time
                        if isinstance(expire_time, str):
                            from dateutil import parser
                            expire_time = parser.parse(expire_time)

                        if expire_time < datetime.now(expire_time.tzinfo):
                            logger.warning(f"  ⚠️ Cache expired at {expire_time}, creating new cache")
                            cached_content_id = await self.get_or_create_cached_content(system_prompt, tools)
                            newly_created_cache = True
                            logger.info(f"  ✓ Created replacement cache: {cached_content_id}")
                        else:
                            logger.info(f"  ✓ Cache is valid until {expire_time}")
                    else:
                        logger.info(f"  ✓ Cache is valid (no expiration info)")

                except Exception as e:
                    logger.warning(f"  ⚠️ Cache validation failed: {e}")
                    logger.info(f"  → Attempting to create new cache")
                    try:
                        cached_content_id = await self.get_or_create_cached_content(system_prompt, tools)
                        newly_created_cache = True
                        logger.info(f"  ✓ Created new cache: {cached_content_id}")
                    except Exception as create_error:
                        logger.error(f"  ❌ Failed to create new cache: {create_error}")
                        logger.warning(f"  → Will proceed without caching")
                        cached_content_id = None

            # FIX #3: Removed file_search_store_id fetching
            # File search store is managed by the search_knowledge_base tool, not the Agent
            # The tool uses environment variable GEMINI_FILE_SEARCH_STORE_NAME directly

            # Determine if we'll use caching
            use_cache = bool(cached_content_id and not cached_content_id.startswith('no_cache_'))
            logger.info(f"\n🔧 STEP 6: Agent creation strategy")
            logger.info(f"  → Use cache: {use_cache}")
            if use_cache:
                logger.info(f"  → Cache ID: {cached_content_id}")
            else:
                logger.info(f"  → Will use full system prompt (no caching)")

            if use_cache:
                logger.info(f"🚀 Initializing GoogleModel with cached content: {cached_content_id}")

                # Create GoogleModelSettings and pass to GoogleModel
                # API: GoogleModel(model_name, settings=GoogleModelSettings(...))
                # Reference: https://ai.pydantic.dev/api/models/google/
                from pydantic_ai.models.google import GoogleModelSettings
                logger.info(f"🎯 Creating GoogleModelSettings with google_cached_content: {cached_content_id}")

                try:
                    # GoogleModelSettings is a TypedDict, create it and pass to GoogleModel
                    settings = GoogleModelSettings(google_cached_content=cached_content_id)
                    logger.info(f"✅ GoogleModelSettings created successfully")
                    logger.info(f"🎯 Settings type: {type(settings)}")
                    logger.info(f"🎯 Settings dict: {settings}")
                except Exception as settings_error:
                    logger.error(f"❌ Failed to create GoogleModelSettings: {settings_error}")
                    logger.error(f"❌ Error type: {type(settings_error)}")
                    logger.error(f"❌ Cached content ID: {cached_content_id}")
                    raise

                # Pass settings to GoogleModel constructor (parameter name is 'settings', not 'model_settings')
                logger.info("🎯 Creating GoogleModel with cached content settings...")
                logger.info(f"🎯 MODEL_NAME: {MODEL_NAME}")
                logger.info(f"🎯 settings type: {type(settings)}")
                logger.info(f"🎯 settings content: {settings}")

                try:
                    # FIX: Parameter name is 'settings', not 'model_settings'
                    google_model = GoogleModel(MODEL_NAME, settings=settings)
                    logger.info("✅ GoogleModel created with cached content")
                    logger.info(f"🎯 GoogleModel type: {type(google_model)}")
                    logger.info(f"🎯 GoogleModel repr: {repr(google_model)}")
                except Exception as model_error:
                    logger.error(f"❌ Failed to create GoogleModel: {model_error}")
                    logger.error(f"❌ Error type: {type(model_error)}")
                    import traceback
                    logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
                    raise

                # Create agent without system_prompt AND without tools (both in cached content)
                # IMPORTANT:
                # 1. Don't pass system_prompt - it's in the cached content
                # 2. Don't pass tools - they're ALSO in the cached content
                # 3. Gemini API error: "CachedContent can not be used with GenerateContent
                #    request setting system_instruction, tools or tool_config"
                logger.info("🎯 About to create Agent with cached content...")
                logger.info(f"🎯 google_model: {google_model}")
                logger.info(f"🎯 Cached content includes {len(tools)} tools - NOT passing to Agent")
                logger.info(f"🎯 deps_type: {ChatSessionDeps}")

                try:
                    # FIX: Omit both system_prompt AND tools when using cached content
                    # Both are already in the cache, passing them causes Gemini API error
                    agent = Agent(
                        google_model,
                        # system_prompt omitted - already in cached content
                        # tools omitted - ALSO in cached content (Gemini requirement)
                        deps_type=ChatSessionDeps
                    )
                    logger.info("✅ Agent created with cached system prompt")
                    logger.info(f"🎯 Agent type: {type(agent)}")
                    logger.info(f"🎯 Agent has system_prompt: {hasattr(agent, 'system_prompt')}")
                    if hasattr(agent, 'system_prompt'):
                        logger.info(f"🎯 Agent system_prompt type: {type(agent.system_prompt)}")
                except Exception as agent_error:
                    logger.error(f"❌ Failed to create Agent: {agent_error}")
                    logger.error(f"❌ Error type: {type(agent_error)}")
                    logger.error(f"❌ Error args: {agent_error.args}")
                    import traceback
                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")
                    raise
            else:
                logger.info("📝 No cache available - using full system prompt")
                logger.info(f"🎯 System prompt length: {len(system_prompt)} characters")

                # Initialize GoogleModel without caching
                logger.info(f"🎯 Creating GoogleModel without cache (MODEL_NAME: {MODEL_NAME})")
                try:
                    google_model = GoogleModel(MODEL_NAME)
                    logger.info("✅ GoogleModel created without cached content")
                    logger.info(f"🎯 GoogleModel type: {type(google_model)}")
                except Exception as model_error:
                    logger.error(f"❌ Failed to create GoogleModel: {model_error}")
                    raise

                # Create agent with full system prompt
                logger.info("🎯 About to create Agent with full system prompt...")
                logger.info(f"🎯 google_model: {google_model}")
                logger.info(f"🎯 tools count: {len(tools)}")
                logger.info(f"🎯 system_prompt preview: {system_prompt[:200]}...")

                try:
                    agent = Agent(
                        google_model,
                        system_prompt=system_prompt,
                        tools=tools,  # Now guaranteed to be a list
                        deps_type=ChatSessionDeps
                    )
                    logger.info("✅ Agent created with full system prompt (no caching)")
                    logger.info(f"🎯 Agent type: {type(agent)}")
                except Exception as agent_error:
                    logger.error(f"❌ Failed to create Agent: {agent_error}")
                    logger.error(f"❌ Error type: {type(agent_error)}")
                    import traceback
                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")
                    raise

            # Save cached_content_id to DB if we created one
            if newly_created_cache and cached_content_id:
                logger.info(f"\n🔧 STEP 7: Saving cache to database")
                logger.info(f"  → Starting background task to save cache ID")
                # Run DB update in background - don't block agent creation
                asyncio.create_task(
                    self._save_cache_to_session_background(session_id, cached_content_id)
                )

            logger.info("="*80)
            logger.info(f"✅ CREATE_AGENT COMPLETED SUCCESSFULLY - Session: {session_id}")
            logger.info(f"   - Agent type: {type(agent).__name__}")
            logger.info(f"   - Tools count: {len(tools)}")
            logger.info(f"   - Used cache: {use_cache}")
            logger.info("="*80)

            return agent

        except Exception as e:
            import traceback
            logger.error(f"❌ Error creating agent: {e}")
            logger.error(f"❌ Error type: {type(e)}")
            logger.error(f"❌ Error args: {e.args}")
            logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
            logger.error(f"❌ Session ID: {session_id}")
            logger.error(f"❌ Tools count: {len(tools) if tools else 0}")
            logger.error(f"❌ System prompt length: {len(system_prompt) if system_prompt else 0}")
            raise

    def _convert_db_messages_to_pydantic_ai(self, db_messages: List[Dict[str, Any]]) -> List[Any]:
        """
        Convert database messages to Pydantic AI message format.

        Args:
            db_messages: List of messages from database with 'role' and 'content' fields

        Returns:
            List of ModelRequest and ModelResponse objects for message_history
        """
        pydantic_messages = []

        for msg in db_messages:
            role = msg.get('role', 'user')
            content = msg.get('message', msg.get('content', ''))

            if role == 'user':
                # Create ModelRequest for user messages
                user_part = UserPromptPart(content=content)
                pydantic_messages.append(ModelRequest(parts=[user_part]))
            elif role in ['assistant', 'agent', 'bot', 'admin']:
                # Create ModelResponse for assistant messages
                text_part = TextPart(content=content)
                model_response = ModelResponse(
                    parts=[text_part],
                    model_name=MODEL_NAME,
                    # Usage is required but we don't have historical data, use zeros
                    usage=Usage(request_tokens=0, response_tokens=0, total_tokens=0)
                )
                pydantic_messages.append(model_response)

        logger.info(f"📝 Converted {len(db_messages)} DB messages to {len(pydantic_messages)} Pydantic AI messages")
        return pydantic_messages

    async def stream_agent_response(self, message: str, session_id: str, tools: List[Any]):
        """Stream agent response using Pydantic AI with RAG, token tracking, and proper error handling."""
        try:
            logger.info(f"🚀 Starting agent stream for session: {session_id}")
            logger.info(f"📝 Message: {message[:100]}...")
            logger.info(f"🔧 Tools received in stream_agent_response: {tools}")
            logger.info(f"🔧 Tools type: {type(tools)}")
            if tools is not None:
                logger.info(f"🔧 Tools length: {len(tools)}")
                for i, tool in enumerate(tools):
                    logger.info(f"🔧 Tool {i} in stream: {tool} (type: {type(tool)})")

            # Create agent with dynamic persona and tools (caching configured at initialization)
            logger.info("🤖 Calling create_agent from stream_agent_response...")
            agent = await self.create_agent(session_id, "", tools)
            logger.info("✅ Agent created successfully")
            logger.info(f"🤖 Agent object: {agent}")
            logger.info(f"🤖 Agent type: {type(agent)}")

            # Create session dependencies
            session_deps = ChatSessionDeps(session_id=session_id)
            logger.info("✅ Session dependencies created")

            # Get chat history for context
            chat_history = await self.get_chat_history(session_id)
            history_count = len(chat_history.get('messages', []))
            logger.info(f"📚 Retrieved {history_count} messages from chat history")

            # Convert database messages to Pydantic AI message format
            message_history = []
            if chat_history and chat_history.get("messages"):
                db_messages = chat_history["messages"]
                logger.info(f"📚 Converting {len(db_messages)} history messages to Pydantic AI format")

                # Skip the first greeting message if it exists
                messages_to_convert = db_messages[1:] if len(db_messages) > 1 else db_messages

                message_history = self._convert_db_messages_to_pydantic_ai(messages_to_convert)
                logger.info(f"✅ Converted to {len(message_history)} Pydantic AI messages")

                # Log preview of history
                for idx, msg in enumerate(messages_to_convert[:5], 1):  # Show first 5
                    sender = msg.get('sender', 'unknown')
                    content = msg.get('message', '')[:50]
                    logger.info(f"  History[{idx}] {sender}: {content}...")

            logger.info(f"📝 Message history count: {len(message_history)}")

            logger.info(f"🤖 Running agent stream...")

            # Use Pydantic AI's run_stream for streaming responses with proper message history
            # Caching is already configured in GoogleModel via GoogleModelSettings
            # Pass message_history to maintain conversation context (prevents greeting on every message)
            full_response_text = ""
            logger.info("🎯 About to call agent.run_stream...")
            logger.info(f"🎯 Passing {len(message_history)} messages as message_history")

            async with agent.run_stream(
                message,  # Just the current message, not with history appended
                deps=session_deps,
                message_history=message_history if message_history else None
            ) as result:
                logger.info("✅ agent.run_stream context entered")
                logger.info(f"🎯 Result object: {result}")
                logger.info(f"🎯 Result type: {type(result)}")
                
                # Stream chunks as they arrive
                # FIX: Use stream_text(delta=True) instead of stream()
                # - stream() is deprecated and returns structured output
                # - stream_text(delta=True) returns incremental text deltas (only new text)
                # - This prevents duplicates and gives proper streaming behavior
                logger.info("🎯 About to iterate over result.stream_text(delta=True)...")
                chunk_count = 0

                async for chunk in result.stream_text(delta=True):
                    chunk_count += 1
                    logger.info(f"🎯 Chunk {chunk_count}: {repr(chunk[:100])}...")  # Log first 100 chars

                    full_response_text += chunk

                    # Format as JSON for frontend compatibility
                    chunk_data = {
                        "type": "chunk",
                        "content": chunk
                    }
                    yield f"{json.dumps(chunk_data)}\n\n"

                logger.info(f"✅ Stream completed - Total chunks: {chunk_count}")
                logger.info(f"✅ Total response length: {len(full_response_text)} chars")
                logger.info(f"✅ Full response preview: {repr(full_response_text[:200])}...")

                # Check for duplications (shouldn't happen with stream_text(delta=True))
                if full_response_text:
                    words = full_response_text.split()[:20]  # First 20 words
                    if len(words) > 0:
                        first_phrase = ' '.join(words)
                        occurrences = full_response_text.count(first_phrase)
                        if occurrences > 1:
                            logger.warning(f"⚠️ DUPLICATE DETECTED: First phrase appears {occurrences} times!")
                            logger.warning(f"⚠️ This shouldn't happen with stream_text(delta=True)")
                            logger.warning(f"⚠️ First phrase: {first_phrase}")
                        else:
                            logger.info(f"✅ No duplicates detected - stream_text(delta=True) working correctly")

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
            import traceback
            logger.error(f"❌ Error in agent stream: {e}")
            logger.error(f"❌ Error type: {type(e)}")
            logger.error(f"❌ Error args: {e.args}")
            logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
            logger.error(f"❌ Session ID: {session_id}")
            logger.error(f"❌ Message preview: {message[:100]}...")

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
