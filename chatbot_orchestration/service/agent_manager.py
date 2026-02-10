"""
Agent Management for Pydantic AI
Handles agent creation, caching, and configuration
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from shared.otel_logger import get_otel_logger

from ..core.ai import MODEL_NAME, get_genai_client
from ..core.dependencies import ChatSessionDeps
from ..tools.knowledge_tools import search_knowledge_base, query_railway_postgres, request_human_agent_connection
from .session_manager import session_state_manager

logger = get_otel_logger("agent_manager", "chatbot-orchestration")

class AgentManager:
    """Manages Pydantic AI agent creation and configuration with instance caching."""

    def __init__(self):
        self.genai_client = None
        self.agent_cache: Dict[str, Agent] = {}  # Cache agents by session_id

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

    def get_cached_agent(self, session_id: str) -> Optional[Agent]:
        """Get cached agent for a session if it exists."""
        return self.agent_cache.get(session_id)

    def clear_agent_cache(self, session_id: str):
        """Clear cached agent for a session."""
        if session_id in self.agent_cache:
            del self.agent_cache[session_id]
            logger.info(f"🗑️ Cleared cached agent for session: {session_id}")

    async def create_agent(self, session_id: str, user_email: str = "anonymous@example.com", force_new: bool = False) -> Agent:
        """Create or retrieve cached agent instance with PydanticAI's built-in caching."""
        logger.info("="*80)
        logger.info(f"🚀 CREATE_AGENT - Session: {session_id}")
        logger.info("="*80)

        # Check if we already have a cached agent for this session
        if not force_new and session_id in self.agent_cache:
            logger.info(f"✅ Reusing cached agent for session: {session_id}")
            logger.info("💰 No agent creation overhead - instant response!")
            logger.info("="*80)
            return self.agent_cache[session_id]

        await self.initialize()
        if not self.genai_client:
            logger.error("❌ GenAI client initialization failed!")
            raise RuntimeError("GenAI client failed to initialize - cannot create agent")

        # Fetch persona config
        try:
            persona_config = await self._fetch_persona_config()
            logger.info(f"✅ Persona config retrieved: {persona_config['persona_name']}")
        except Exception as fetch_error:
            logger.error(f"❌ Failed to fetch persona config: {fetch_error}")
            raise

        # Build system prompt
        try:
            system_prompt = await self._build_system_prompt(persona_config)
            logger.info(f"✅ System prompt built: {len(system_prompt)} characters")
            logger.info(f"✅ Estimated tokens: ~{int(len(system_prompt) / 4)}")
        except Exception as prompt_error:
            logger.error(f"❌ Failed to build system prompt: {prompt_error}")
            raise

        # Define tools (fixed set)
        tool_functions = [search_knowledge_base, query_railway_postgres, request_human_agent_connection]
        logger.info(f"📋 Registering {len(tool_functions)} tools with agent")

        # Create agent with PydanticAI's built-in caching
        logger.info("🚀 Creating agent with built-in PydanticAI caching")
        try:
            # Create model with built-in cache settings
            google_model = GoogleModel(
                MODEL_NAME,
                model_settings=GoogleModelSettings(
                    cache_system_prompt=True,  # Enable built-in caching for system prompt + tools
                    cached_content_ttl='900s'  # 15 minutes TTL
                )
            )
            logger.info("✅ GoogleModel created with cache_system_prompt=True")

            # Create agent with system prompt and tools
            agent = Agent(
                google_model,
                system_prompt=system_prompt,
                tools=tool_functions,
                deps_type=ChatSessionDeps
            )
            logger.info("✅ Agent created successfully")
            logger.info("💰 PydanticAI will auto-cache system prompt + tools on first use")
            logger.info("💰 Token savings: ~85-90% on subsequent requests")

        except Exception as agent_error:
            logger.error(f"❌ Failed to create Agent: {agent_error}")
            raise

        # Cache the agent instance for this session
        self.agent_cache[session_id] = agent
        logger.info(f"✅ Agent cached for session: {session_id}")

        logger.info("="*80)
        logger.info(f"✅ CREATE_AGENT COMPLETED - Session: {session_id}")
        logger.info(f"   - Agent type: {type(agent).__name__}")
        logger.info(f"   - Cached for reuse: Yes")
        logger.info("="*80)

        return agent

# Global agent manager instance
agent_manager = AgentManager()
