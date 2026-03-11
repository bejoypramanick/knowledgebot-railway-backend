"""
Agent Management for Pydantic AI
Handles agent creation, caching, and configuration
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel
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
        """Fetch persona configuration from the configuration service."""
        try:
            # Fetch from configuration service
            import httpx
            from ..core.config import get_settings
            
            settings = get_settings()
            config_service_url = settings.configuration_service_url
            
            logger.info(f"🔍 Fetching persona config from: {config_service_url}")
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"{config_service_url}/api/v1/configuration/chatAgentConfig",
                    timeout=5.0
                )
                
                if response.status_code == 200:
                    config_data = response.json().get('data', {})
                    
                    # Extract persona information
                    persona_data = config_data.get('persona', {})
                    system_prompt = persona_data.get('system_prompt', '')
                    selected_persona = persona_data.get('selected_persona', 'KnowledgeBot')
                    
                    logger.info(f"✅ Fetched persona config: {selected_persona}")
                    logger.info(f"   System prompt length: {len(system_prompt)} characters")
                    
                    return {
                        "persona_name": selected_persona,
                        "persona_description": f"Persona: {selected_persona}",
                        "system_instructions": system_prompt  # This is the custom prompt from the UI
                    }
                else:
                    logger.warning(f"⚠️ Configuration service returned status {response.status_code}")
                    # Fall back to default
                    return self._get_default_persona_config()
                    
        except Exception as e:
            logger.error(f"❌ Failed to fetch persona config from configuration service: {e}")
            # Return fallback persona
            return self._get_default_persona_config()
    
    def _get_default_persona_config(self) -> Dict[str, Any]:
        """Return default persona configuration."""
        return {
            "persona_name": "Knowledge Bot",
            "persona_description": "A helpful AI assistant that can search knowledge bases and answer questions",
            "system_instructions": "You are a helpful AI assistant. Always provide accurate, well-formatted responses using HTML tags."
        }

    async def _build_system_prompt(self, persona_config: Dict[str, Any]) -> str:
        """Build system prompt from persona configuration."""
        try:
            # Import the system prompt generator
            from ..agent.prompt import get_system_prompt

            # Extract custom prompt from persona config if available
            custom_prompt = persona_config.get('system_instructions', None)

            # Get the comprehensive system prompt
            # This includes all RAG enforcement rules (critical enforcement at top of prompt)
            base_prompt = get_system_prompt(custom_prompt=custom_prompt, response_policy=None)

            # No additional overrides - prompt.py handles all critical rules
            # Single source of truth prevents inconsistency and maintenance burden
            return base_prompt
        except Exception as e:
            logger.error(f"❌ Failed to build system prompt: {e}")
            # Return fallback system prompt
            return f"""You are {persona_config.get('persona_name', 'Assistant')}.
            {persona_config.get('persona_description', 'You are a helpful AI assistant.')}

            Always provide helpful, accurate responses using proper HTML formatting."""

    def get_cached_agent(self, session_id: str) -> Optional[Agent]:
        """Get cached agent for a session if it exists."""
        return self.agent_cache.get(session_id)

    def clear_agent_cache(self, session_id: str = None):
        """Clear cached agent for a session or all sessions.
        
        Args:
            session_id: If provided, clear only this session's cache. If None, clear all caches.
        """
        if session_id:
            if session_id in self.agent_cache:
                del self.agent_cache[session_id]
                logger.info(f"🗑️ Cleared cached agent for session: {session_id}")
        else:
            # Clear all cached agents
            cache_size = len(self.agent_cache)
            self.agent_cache.clear()
            logger.info(f"🗑️ Cleared all cached agents ({cache_size} sessions)")

    async def create_agent(self, session_id: str, user_email: str = "anonymous@example.com", force_new: bool = False) -> Agent:
        """Create or retrieve cached agent instance with PydanticAI's built-in caching.
        
        Args:
            session_id: The session ID
            user_email: The user's email
            force_new: If True, always create a fresh agent (ignoring cache). Use this when persona changes.
        """
        logger.info("="*80)
        logger.info(f"🚀 CREATE_AGENT - Session: {session_id}")
        logger.info(f"   force_new: {force_new}")
        logger.info("="*80)

        # Check if we already have a cached agent for this session
        # Force new agent if tools are needed to ensure fresh tool state
        if session_id in self.agent_cache and not force_new:
            logger.info(f"✅ Reusing cached agent for session: {session_id}")
            logger.info("💰 No agent creation overhead - instant response!")
            logger.info("="*80)
            return self.agent_cache[session_id]
        
        # Clear existing cache if forcing new agent
        if force_new and session_id in self.agent_cache:
            del self.agent_cache[session_id]
            logger.info(f"🗑️ Cleared cached agent for session: {session_id} (force_new=True)")

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

        # Create agent (caching will be enabled at runtime via model_settings)
        logger.info("🚀 Creating agent for session")
        try:
            # Create model
            google_model = GoogleModel(MODEL_NAME)
            logger.info("✅ GoogleModel created")

            # Create agent with system prompt and tools
            # Use end_strategy='exhaustive' to ensure ALL tools execute, not just first output
            # This fixes issue where Gemini returns text instead of calling tools
            agent = Agent(
                google_model,
                system_prompt=system_prompt,
                tools=tool_functions,
                deps_type=ChatSessionDeps,
                end_strategy='exhaustive'  # Ensure tools execute even after initial output
            )
            logger.info("✅ Agent created successfully")
            logger.info(f"📝 System prompt: {len(system_prompt)} chars")
            logger.info(f"📝 System prompt preview: {system_prompt[:200]}...")
            logger.info(f"📝 Has HTML formatting instructions: {'MANDATORY HTML FORMATTING' in system_prompt}")
            logger.info("ℹ️ Caching will be enabled via model_settings in run_stream()")
            logger.info("💰 Token savings: ~85-90% when cache_system_prompt=True is used")

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
