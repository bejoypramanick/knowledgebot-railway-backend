"""
Agent Management for Pydantic AI
Handles agent creation, caching, and configuration
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from shared.otel_logger import get_otel_logger

from ..core.ai import MODEL_NAME, get_genai_client
from ..core.dependencies import ChatSessionDeps
from ..tools.knowledge_tools import search_knowledge_base, query_railway_postgres, request_human_agent_connection
from .session_manager import session_state_manager

logger = get_otel_logger("agent_manager", "chatbot-orchestration")

class AgentManager:
    """Manages Pydantic AI agent creation and configuration."""

    def __init__(self):
        self.genai_client = None

    async def initialize(self):
        """Initialize the agent manager."""
        if not self.genai_client:
            self.genai_client = get_genai_client()

    async def _fetch_persona_config(self) -> Dict[str, Any]:
        """Fetch persona configuration for the agent."""
        try:
            # For now, return default persona
            # In the future, this could fetch from database or config service
            return {
                "persona_name": "Knowledge Bot",
                "persona_description": "A helpful AI assistant that can search knowledge bases and answer questions",
                "system_instructions": "You are a helpful AI assistant. Always provide accurate, well-formatted responses using HTML tags."
            }
        except Exception as e:
            logger.error(f"❌ Failed to fetch persona config: {e}")
            # Return fallback persona
            return {
                "persona_name": "Assistant",
                "persona_description": "AI Assistant",
                "system_instructions": "You are a helpful AI assistant."
            }

    async def _build_system_prompt(self, persona_config: Dict[str, Any]) -> str:
        """Build system prompt from persona configuration."""
        try:
            # Import the system prompt generator
            from ..agent.prompt import get_system_prompt

            # Extract custom prompt from persona config if available
            custom_prompt = persona_config.get('system_instructions', None)

            # Get the comprehensive system prompt
            return get_system_prompt(custom_prompt=custom_prompt, response_policy=None)
        except Exception as e:
            logger.error(f"❌ Failed to build system prompt: {e}")
            # Return fallback system prompt
            return f"""You are {persona_config.get('persona_name', 'Assistant')}.
            {persona_config.get('persona_description', 'You are a helpful AI assistant.')}

            Always provide helpful, accurate responses using proper HTML formatting."""

    async def create_agent(self, session_id: str, user_email: str = "anonymous@example.com") -> Agent:
        """Create an agent instance with proper Pydantic AI settings and caching."""
        logger.info("="*80)
        logger.info(f"🚀 CREATE_AGENT STARTED - Session: {session_id}")
        logger.info("="*80)

        await self.initialize()
        if not self.genai_client:
            logger.error("❌ GenAI client initialization failed!")
            raise RuntimeError("GenAI client failed to initialize - cannot create agent")

        # Fetch persona config and cached content ID
        try:
            persona_config, cached_content_id = await asyncio.gather(
                self._fetch_persona_config(),
                session_state_manager.get_cached_content_id(session_id),
                return_exceptions=False
            )
            logger.info(f"✅ Persona config retrieved: {persona_config['persona_name']}")
            logger.info(f"✅ Cached content ID: {cached_content_id if cached_content_id else 'None (will create new)'}")
        except Exception as fetch_error:
            logger.error(f"❌ Failed to fetch persona/cache: {fetch_error}")
            raise

        # Build system prompt
        try:
            system_prompt = await self._build_system_prompt(persona_config)
            logger.info(f"✅ System prompt built: {len(system_prompt)} characters")
            logger.info(f"✅ Estimated tokens: ~{int(len(system_prompt) / 4)}")
        except Exception as prompt_error:
            logger.error(f"❌ Failed to build system prompt: {prompt_error}")
            raise

        # Define tools (fixed set - perfect for caching)
        tool_functions = [search_knowledge_base, query_railway_postgres, request_human_agent_connection]
        logger.info(f"📋 Using {len(tool_functions)} tools for agent")

        # Cache validation and management
        newly_created_cache = False
        use_cache = False

        if not cached_content_id or cached_content_id.startswith('no_cache_'):
            logger.info("→ No valid cache found, creating new cached content (prompt + tool schemas)")
            try:
                cached_content_id = await session_state_manager.get_or_create_cached_content(
                    system_prompt,
                    tool_functions=tool_functions
                )
                newly_created_cache = True
                logger.info(f"✅ Created new cached content: {cached_content_id}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to create cached content: {e}")
                cached_content_id = None
        else:
            logger.info(f"→ Validating existing cache: {cached_content_id}")
            try:
                cache_info = self.genai_client.caches.get(cached_content_id)
                logger.info("✅ Cache found, checking expiration")
                if hasattr(cache_info, 'expire_time'):
                    expire_time = cache_info.expire_time
                    if isinstance(expire_time, str):
                        from dateutil import parser
                        expire_time = parser.parse(expire_time)
                    if expire_time < datetime.now(expire_time.tzinfo):
                        logger.warning(f"⚠️ Cache expired at {expire_time}, creating new cache")
                        cached_content_id = await session_state_manager.get_or_create_cached_content(
                            system_prompt,
                            tool_functions=tool_functions
                        )
                        newly_created_cache = True
                        logger.info(f"✅ Created replacement cache: {cached_content_id}")
                    else:
                        logger.info(f"✅ Cache is valid until {expire_time}")
                else:
                    logger.info("✅ Cache is valid (no expiration info)")
            except Exception as e:
                logger.warning(f"⚠️ Cache validation failed: {e}")
                try:
                    cached_content_id = await session_state_manager.get_or_create_cached_content(
                        system_prompt,
                        tool_functions=tool_functions
                    )
                    newly_created_cache = True
                    logger.info(f"✅ Created new cache: {cached_content_id}")
                except Exception as create_error:
                    logger.error(f"❌ Failed to create new cache: {create_error}")
                    cached_content_id = None

        # Determine cache usage - enable caching for 90% token cost reduction
        use_cache = bool(cached_content_id and not cached_content_id.startswith('no_cache_'))

        if use_cache:
            logger.info("✅ Cache available - using cached system prompt for 90% cost reduction")
            logger.info(f"✅ Cache ID: {cached_content_id}")
        else:
            logger.info("ℹ️ No cache available - will use full system prompt")

        # Create agent
        logger.info(f"\n🔧 STEP 6: Agent creation strategy")
        logger.info(f"  → Use cache: {use_cache}")

        if use_cache:
            # Create agent with cached content
            logger.info("🚀 Initializing GoogleModel with cached content")
            try:
                settings = GoogleModelSettings(google_cached_content=cached_content_id)
                logger.info("✅ GoogleModelSettings created successfully")
            except Exception as settings_error:
                logger.error(f"❌ Failed to create GoogleModelSettings: {settings_error}")
                raise

            try:
                google_model = GoogleModel(MODEL_NAME, settings=settings)
                logger.info("✅ GoogleModel created with cached content")
            except Exception as model_error:
                logger.error(f"❌ Failed to create GoogleModel: {model_error}")
                raise

            try:
                # IMPORTANT: When using cached content, do NOT pass tools or system_prompt
                # They are already in the cache and passing them causes 400 error
                agent = Agent(
                    google_model,
                    deps_type=ChatSessionDeps
                    # Note: system_prompt + tools are in cached content - do NOT pass here!
                )
                logger.info("✅ Agent created with cached content (system prompt + tool schemas)")
                logger.info("💰 Token savings: ~90% (cached prompt + tool schemas)")
                logger.info("⚠️ Tools NOT passed to Agent - they're in the cache!")
            except Exception as agent_error:
                logger.error(f"❌ Failed to create Agent: {agent_error}")
                raise
        else:
            # Create agent with full system prompt
            logger.info("📝 No cache available - using full system prompt")
            logger.info(f"🎯 System prompt length: {len(system_prompt)} characters")
            
            try:
                google_model = GoogleModel(MODEL_NAME)
                logger.info("✅ GoogleModel created without cached content")
            except Exception as model_error:
                logger.error(f"❌ Failed to create GoogleModel: {model_error}")
                raise

            try:
                agent = Agent(
                    google_model,
                    system_prompt=system_prompt,
                    tools=tool_functions,
                    deps_type=ChatSessionDeps
                )
                logger.info("✅ Agent created with full system prompt + tools (no caching)")
            except Exception as agent_error:
                logger.error(f"❌ Failed to create Agent: {agent_error}")
                raise

        # Save cache to database if newly created
        if newly_created_cache and cached_content_id:
            logger.info(f"\n🔧 STEP 7: Saving cache to database")
            asyncio.create_task(
                session_state_manager._save_cache_to_session_background(session_id, cached_content_id)
            )

        logger.info("="*80)
        logger.info(f"✅ CREATE_AGENT COMPLETED SUCCESSFULLY - Session: {session_id}")
        logger.info(f"   - Agent type: {type(agent).__name__}")
        logger.info(f"   - Used cache: {use_cache}")
        logger.info("="*80)

        return agent

# Global agent manager instance
agent_manager = AgentManager()
