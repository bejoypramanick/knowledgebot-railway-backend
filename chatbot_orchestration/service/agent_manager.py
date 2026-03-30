"""
Agent Management for Pydantic AI
Handles agent creation, caching, and configuration
"""

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic_ai import Agent
from shared.otel_logger import get_otel_logger

from ..core.ai import get_genai_client
from ..core.dependencies import ChatSessionDeps
from .session_manager import session_state_manager
from ..tools.vector_search_tool import search_knowledge_base

logger = get_otel_logger("agent_manager", "chatbot-orchestration")


class AgentManager:
    """Manages Pydantic AI agent creation and configuration with instance caching."""

    def __init__(self):
        self.genai_client = None
        self.agent_cache: Dict[str, Agent] = {}  # Cache agents by session_id
        self.system_prompt_cache: Dict[
            str, str
        ] = {}  # Cache system prompts by session_id

    async def initialize(self):
        """Initialize the agent manager."""
        if not self.genai_client:
            self.genai_client = get_genai_client()

    async def _fetch_persona_config(self) -> Dict[str, Any]:
        """Fetch persona configuration and response policy from the database at runtime."""
        try:
            # Query the database directly for the active persona and its system prompt
            from shared.sqlalchemy_db import get_db_session
            from sqlalchemy import text

            logger.info(
                f"🔍 Fetching active persona and response policy from database..."
            )

            async with get_db_session() as db_session:
                # Query for the active persona configuration
                query = """
                    SELECT persona_name, system_prompt 
                    FROM persona_configurations 
                    WHERE is_active = true 
                    LIMIT 1
                """
                result = await db_session.execute(text(query))
                row = result.mappings().first()

                # Query for response policy from security settings
                policy_query = """
                    SELECT setting_value 
                    FROM security_settings 
                    WHERE setting_name = 'response_policy' 
                    LIMIT 1
                """
                policy_result = await db_session.execute(text(policy_query))
                policy_row = policy_result.mappings().first()

                # Parse response policy (convert from string to float, default to 0.5)
                response_policy = 0.5
                if policy_row:
                    try:
                        policy_value = float(policy_row["setting_value"])

                        # Validate and clamp to 0-1 range
                        if 0 <= policy_value <= 1:
                            response_policy = policy_value
                        elif policy_value > 1:
                            # If stored as percentage (e.g., 60), convert to fraction (0.6)
                            response_policy = policy_value / 100.0
                            logger.warning(
                                f"⚠️ response_policy was > 1 ({policy_value}), converted to {response_policy}"
                            )
                        else:
                            response_policy = 0.5
                            logger.warning(
                                f"⚠️ response_policy out of range: {policy_value}, using default 0.5"
                            )

                        # Clamp to valid range and enforce minimum sensible temperature
                        MIN_TEMPERATURE = 0.1  # Prevent extremely low temperatures
                        response_policy = max(0.0, min(1.0, response_policy))
                        if policy_value < MIN_TEMPERATURE:
                            logger.warning(
                                f"⚠️ response_policy was suspiciously low ({policy_value}), clamping to {MIN_TEMPERATURE}"
                            )
                            response_policy = MIN_TEMPERATURE
                        logger.info(
                            f"✅ Fetched response_policy from database: {response_policy}"
                        )
                    except (ValueError, TypeError):
                        logger.warning(
                            f"⚠️ Could not parse response_policy value: {policy_row['setting_value']}, using default 0.5"
                        )
                else:
                    logger.info(
                        f"ℹ️ No response_policy found in database, using default: 0.5"
                    )

                if row:
                    persona_name = row["persona_name"]
                    system_prompt = row["system_prompt"] or ""

                    logger.info(
                        f"✅ Fetched active persona from database: {persona_name}"
                    )
                    logger.info(
                        f"   System prompt length: {len(system_prompt)} characters"
                    )
                    logger.info(f"   Response policy: {response_policy}")

                    return {
                        "persona_name": persona_name,
                        "persona_description": f"Persona: {persona_name}",
                        "system_instructions": system_prompt,  # This is the custom prompt from the database
                        "response_policy": response_policy,  # Response policy (0-1 range)
                    }
                else:
                    logger.warning(f"⚠️ No active persona found in database")
                    # Fall back to default
                    return self._get_default_persona_config()

        except Exception as e:
            logger.error(f"❌ Failed to fetch persona config from database: {e}")
            # Return fallback persona
            return self._get_default_persona_config()

    def _get_default_persona_config(self) -> Dict[str, Any]:
        """Return default persona configuration."""
        return {
            "persona_name": "Knowledge Bot",
            "persona_description": "A helpful AI assistant that can search knowledge bases and answer questions",
            "system_instructions": "You are a helpful AI assistant. Always provide accurate, well-formatted responses using HTML tags.",
            "response_policy": 0.5,  # Default to balanced (0.5 on 0-1 scale)
        }

    async def _build_system_prompt(self, persona_config: Dict[str, Any]) -> str:
        """Build system prompt from persona configuration."""
        try:
            # Import the system prompt generator
            from ..agent.prompt import get_system_prompt

            # Extract custom prompt from persona config if available
            custom_prompt = persona_config.get("system_instructions", None)

            # Extract response policy (0-1 range, default to 0.5)
            response_policy = persona_config.get("response_policy", 0.5)
            logger.info(f"📊 Using response_policy: {response_policy}")

            # Get the comprehensive system prompt
            # This includes all RAG enforcement rules (critical enforcement at top of prompt)
            base_prompt = get_system_prompt(
                custom_prompt=custom_prompt, response_policy=response_policy
            )

            # No additional overrides - prompt.py handles all critical rules
            # Single source of truth prevents inconsistency and maintenance burden
            return base_prompt
        except Exception as e:
            logger.error(f"❌ Failed to build system prompt: {e}")
            # Return fallback system prompt
            return f"""You are {persona_config.get("persona_name", "Assistant")}.
            {persona_config.get("persona_description", "You are a helpful AI assistant.")}

            Always provide helpful, accurate responses using proper HTML formatting."""

    def get_cached_agent(self, session_id: str) -> Optional[Agent]:
        """Get cached agent for a session if it exists."""
        return self.agent_cache.get(session_id)

    def get_cached_system_prompt(self, session_id: str) -> Optional[str]:
        """Get cached system prompt for a session if it exists."""
        return self.system_prompt_cache.get(session_id)

    def get_cache_diag(self, session_id: str) -> Dict[str, Any]:
        if not hasattr(self, "cache_diag_cache"):
            self.cache_diag_cache = {}
        return dict(self.cache_diag_cache.get(session_id) or {})

    async def ensure_session_cache(self, session_id: str) -> Optional[str]:
        """Ensure an explicit Gemini cache exists for this session's current system prompt and tools."""
        if not hasattr(self, "cache_diag_cache"):
            self.cache_diag_cache = {}
        system_prompt = self.get_cached_system_prompt(session_id)
        if not system_prompt:
            logger.warning(
                f"No cached system prompt available to rebuild Gemini cache for session: {session_id}"
            )
            self.set_cached_cache_name(session_id, None)
            self.cache_diag_cache[session_id] = {
                "create_attempts": 0,
                "create_failures": 1,
                "reused_existing": False,
                "recreated_remote": False,
                "last_error": "missing_cached_system_prompt",
            }
            return None

        try:
            from ..core.cache_manager import gemini_cache_manager

            model_name = os.getenv("CHATBOT_MODEL", "gemini-2.5-flash-lite")
            cache_name = await gemini_cache_manager.ensure_cache(
                system_prompt=system_prompt,
                tool_functions=[search_knowledge_base],
                model_name=model_name,
            )
            self.cache_diag_cache[session_id] = (
                gemini_cache_manager.get_last_ensure_stats()
            )
            self.set_cached_cache_name(session_id, cache_name)
            if cache_name:
                await gemini_cache_manager.register_session(session_id)
                logger.info(
                    f"Ensured Gemini cache for session {session_id}: {cache_name}"
                )
            else:
                logger.warning(
                    f"Gemini cache unavailable after ensure for session {session_id}"
                )
            return cache_name
        except Exception as cache_error:
            logger.warning(
                f"Failed to ensure Gemini cache for session {session_id}: {cache_error}"
            )
            self.set_cached_cache_name(session_id, None)
            self.cache_diag_cache[session_id] = {
                "create_attempts": 0,
                "create_failures": 1,
                "reused_existing": False,
                "recreated_remote": False,
                "last_error": str(cache_error)[:240],
            }
            return None

    async def clear_agent_cache(self, session_id: str = None):
        """Clear cached agent for a session or all sessions.

        Args:
            session_id: If provided, clear only this session's cache. If None, clear all caches.
        """
        if session_id:
            from ..core.cache_manager import gemini_cache_manager

            if session_id in self.agent_cache:
                del self.agent_cache[session_id]
                logger.info(f"Cleared cached agent for session: {session_id}")
            if session_id in self.system_prompt_cache:
                del self.system_prompt_cache[session_id]
            if (
                hasattr(self, "cache_diag_cache")
                and session_id in self.cache_diag_cache
            ):
                del self.cache_diag_cache[session_id]
            if (
                hasattr(self, "cache_name_cache")
                and session_id in self.cache_name_cache
            ):
                del self.cache_name_cache[session_id]
            remaining_sessions = await gemini_cache_manager.unregister_session(
                session_id
            )
            if remaining_sessions == 0:
                logger.info(
                    "Last tracked session cleared; deleting active Gemini cache"
                )
                await gemini_cache_manager.delete_cache()
        else:
            from ..core.cache_manager import gemini_cache_manager

            cache_size = len(self.agent_cache)
            self.agent_cache.clear()
            self.system_prompt_cache.clear()
            if hasattr(self, "cache_diag_cache"):
                self.cache_diag_cache.clear()
            if hasattr(self, "cache_name_cache"):
                self.cache_name_cache.clear()
            await gemini_cache_manager.clear_session_registry()
            await gemini_cache_manager.delete_cache()
            logger.info(f"Cleared all caches ({cache_size} sessions)")

    async def create_agent(
        self,
        session_id: str,
        user_email: str = "anonymous@example.com",
        force_new: bool = False,
    ) -> Agent:
        """Create or retrieve cached agent instance with PydanticAI's built-in caching.

        Args:
            session_id: The session ID
            user_email: The user's email
            force_new: If True, always create a fresh agent (ignoring cache). Use this when persona changes.
        """
        logger.info("=" * 80)
        logger.info(f"🚀 CREATE_AGENT - Session: {session_id}")
        logger.info(f"   force_new: {force_new}")
        logger.info("=" * 80)

        # Check if we already have a cached agent for this session
        # Force new agent if tools are needed to ensure fresh tool state
        if session_id in self.agent_cache and not force_new:
            await self.ensure_session_cache(session_id)
            logger.info(f"✅ Reusing cached agent for session: {session_id}")
            logger.info("💰 No agent creation overhead - instant response!")
            logger.info("=" * 80)
            return self.agent_cache[session_id]

        # Clear existing cache if forcing new agent
        if force_new and session_id in self.agent_cache:
            del self.agent_cache[session_id]
            logger.info(
                f"🗑️ Cleared cached agent for session: {session_id} (force_new=True)"
            )

        await self.initialize()
        if not self.genai_client:
            logger.error("❌ GenAI client initialization failed!")
            raise RuntimeError(
                "GenAI client failed to initialize - cannot create agent"
            )

        # Fetch persona config
        try:
            persona_config = await self._fetch_persona_config()
            logger.info(
                f"✅ Persona config retrieved: {persona_config['persona_name']}"
            )
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

        # Create Gemini explicit context cache (system prompt + tool declarations)
        cache_name = None
        try:
            from ..core.cache_manager import gemini_cache_manager

            # Extract standard model name from get_model or env
            model_name = os.getenv("CHATBOT_MODEL", "gemini-2.5-flash-lite")
            cache_name = await gemini_cache_manager.ensure_cache(
                system_prompt=system_prompt,
                tool_functions=[search_knowledge_base],
                model_name=model_name,
            )
            if cache_name:
                logger.info(f"Gemini cache active: {cache_name}")
            else:
                raise RuntimeError("Gemini cache is required but could not be created")
        except Exception as cache_error:
            logger.error(f"Gemini cache creation failed: {cache_error}")
            raise

        # Get standard model wrapper based on chosen LLM
        logger.info("Creating agent for session")
        try:
            from ..core.cached_google_model import CachedGoogleModel

            model_name = os.getenv("CHATBOT_MODEL", "gemini-2.5-flash-lite")
            model = CachedGoogleModel(model_name)

            if not model:
                raise RuntimeError("Failed to initialize model provider")

            agent = Agent(
                model,
                output_type=str,
                system_prompt=system_prompt,
                tools=[search_knowledge_base],
                deps_type=ChatSessionDeps,
                end_strategy="exhaustive",
            )
            logger.info(f"Agent created (system prompt: {len(system_prompt)} chars)")
            logger.info(f"Agent registered tools: [search_knowledge_base]")

        except Exception as agent_error:
            logger.error(f"Failed to create Agent: {agent_error}")
            raise

        # Cache the agent instance and related data for this session
        self.agent_cache[session_id] = agent
        self.system_prompt_cache[session_id] = system_prompt
        # Store cache_name locally if cached
        if not hasattr(self, "cache_name_cache"):
            self.cache_name_cache = {}
        self.cache_name_cache[session_id] = cache_name

        logger.info(f"Agent cached for session: {session_id}")

        logger.info(f"CREATE_AGENT COMPLETED - Session: {session_id}")

        return agent

    def get_cached_cache_name(self, session_id: str) -> Optional[str]:
        """Get cached Gemini context cache_name if it exists."""
        if hasattr(self, "cache_name_cache"):
            return self.cache_name_cache.get(session_id)
        return None

    def set_cached_cache_name(self, session_id: str, cache_name: Optional[str]) -> None:
        """Update the cached Gemini context cache_name for a session."""
        if not hasattr(self, "cache_name_cache"):
            self.cache_name_cache = {}
        self.cache_name_cache[session_id] = cache_name


# Global agent manager instance
agent_manager = AgentManager()
