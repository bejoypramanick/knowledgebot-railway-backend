"""
Main Agent Service - Simplified after refactoring
This is the main entry point for agent operations
"""

from typing import AsyncGenerator, List, Any

from shared.otel_logger import get_otel_logger

from .agent_manager import agent_manager
from .streaming_service import streaming_service

logger = get_otel_logger("agent_service", "chatbot-orchestration")

class PydanticAIGatewayService:
    """Main service class for Pydantic AI integration with Gemini FileSearch.
    
    This is the simplified main service after refactoring.
    Most functionality has been moved to specialized modules:
    - AgentManager: handles agent creation and configuration
    - StreamingService: handles streaming responses
    - SessionStateManager: handles session state and caching
    - KnowledgeTools: contains all tool implementations
    """

    def __init__(self):
        """Initialize the service with required components."""
        logger.info("🚀 Initializing PydanticAIGatewayService")
        # All components are initialized as global instances in their respective modules

    async def initialize(self):
        """Initialize all service components."""
        await agent_manager.initialize()
        await streaming_service.initialize() if hasattr(streaming_service, 'initialize') else None
        logger.info("✅ PydanticAIGatewayService initialized")

    # Note: create_agent is internal - not exposed publicly
    # All chat interactions must use stream_agent_response

    async def stream_agent_response(
        self,
        message: str,
        session_id: str,
        user_email: str = "anonymous@example.com"
    ) -> AsyncGenerator[str, None]:
        """Stream agent response (ONLY streaming is supported)."""
        logger.info(f"🌊 Starting stream for session: {session_id}")

        # Create agent (tools are configured internally)
        agent = await agent_manager.create_agent(session_id, "", user_email)

        # Stream response
        async for chunk in streaming_service.stream_agent_response(
            agent, message, session_id, user_email
        ):
            yield chunk

    # Legacy methods for backward compatibility
    async def get_session_metadata(self, session_id: str):
        """Get session metadata - delegates to SessionStateManager."""
        return await agent_manager.session_state_manager.get_session_metadata(session_id)

    async def get_cached_content_id(self, session_id: str):
        """Get cached content ID - delegates to SessionStateManager."""
        return await agent_manager.session_state_manager.get_cached_content_id(session_id)

    async def get_chat_history(self, session_id: str):
        """Get chat history - delegates to SessionStateManager."""
        return await session_state_manager.get_chat_history(session_id)
