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

    async def create_agent(self, session_id: str, system_prompt: str = "", tools: List[Any] = None, user_email: str = "anonymous@example.com"):
        """Create an agent instance - delegates to AgentManager."""
        logger.info(f"🤖 Creating agent for session: {session_id}")
        # Note: tools parameter is ignored - tools are hardcoded in AgentManager
        return await agent_manager.create_agent(session_id, system_prompt, user_email)

    async def stream_agent_response(
        self,
        message: str,
        session_id: str,
        tools: List[Any] = None,
        user_email: str = "anonymous@example.com"
    ) -> AsyncGenerator[str, None]:
        """Stream agent response - delegates to StreamingService."""
        logger.info(f"🌊 Starting stream for session: {session_id}")

        # Create agent first (tools parameter ignored - hardcoded in AgentManager)
        agent = await agent_manager.create_agent(session_id, "", user_email)
        
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

    async def process_message(self, message: str, session_id: str) -> str:
        """Process a message and return response (non-streaming)."""
        logger.info(f"📝 Processing message for session: {session_id}")

        # Create agent
        agent = await agent_manager.create_agent(session_id, "", "anonymous@example.com")

        # Get session dependencies
        from ..core.dependencies import ChatSessionDeps
        session_deps = ChatSessionDeps(session_id=session_id)

        # Get chat history
        chat_history = await agent_manager.session_state_manager.get_chat_history(session_id)

        # Convert to Pydantic AI format
        from .streaming_service import streaming_service
        pydantic_messages = streaming_service._convert_db_messages_to_pydantic_ai(chat_history)

        # Run agent
        result = await agent.run(message, message_history=pydantic_messages, deps=session_deps)

        # Extract response text
        response_text = result.data if hasattr(result, 'data') else str(result)

        # Save messages
        await agent_manager.session_state_manager.save_message(session_id, "user", message)
        await agent_manager.session_state_manager.save_message(session_id, "assistant", response_text)

        return response_text

    async def get_available_agents(self) -> list:
        """Get list of available agents."""
        # Return default agent info
        return [
            {
                "agent_id": "default",
                "name": "Knowledge Bot",
                "description": "AI assistant with access to knowledge base and database",
                "capabilities": ["knowledge_base_search", "database_query", "human_escalation"],
                "status": "active"
            }
        ]

    async def get_agent_info(self, agent_id: str) -> dict:
        """Get information about a specific agent."""
        agents = await self.get_available_agents()
        for agent in agents:
            if agent["agent_id"] == agent_id:
                return agent
        return None

    async def run_agent_with_fallback(self, agent, user_message: str, session_deps):
        """Run agent with fallback logic for backward compatibility."""
        from ..core.dependencies import ChatSessionDeps

        logger.info(f"🤖 Running agent with fallback for message: {user_message[:100]}...")

        # Get chat history
        chat_history = await agent_manager.session_state_manager.get_chat_history(session_deps.session_id)

        # Convert to Pydantic AI format
        from .streaming_service import streaming_service
        pydantic_messages = streaming_service._convert_db_messages_to_pydantic_ai(chat_history)

        # Run agent
        result = await agent.run(user_message, message_history=pydantic_messages, deps=session_deps)

        logger.info(f"✅ Agent run completed successfully")
        return result
