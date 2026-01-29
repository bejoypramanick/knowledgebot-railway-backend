import asyncio
from typing import Dict, Set

from configuration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class SSEConnectionManager:
    """Manages SSE connections for real-time chat between agents and customers."""

    def __init__(self):
        # Map session_id -> Set of SSE response objects
        self.active_connections: Dict[str, Set[object]] = {}
        # Map SSE response -> session_id for quick lookup
        self.connection_sessions: Dict[object, str] = {}
        # Map SSE response -> user_type ('agent' or 'customer')
        self.connection_types: Dict[object, str] = {}
        # Map SSE response -> queue for sending messages
        self.message_queues: Dict[object, asyncio.Queue] = {}
        self.lock = asyncio.Lock()

    async def connect(self, response, session_id: str, user_type: str = 'customer'):
        """Connect an SSE response to a session."""
        async with self.lock:
            if session_id not in self.active_connections:
                self.active_connections[session_id] = set()
            self.active_connections[session_id].add(response)
            self.connection_sessions[response] = session_id
            self.connection_types[response] = user_type
            self.message_queues[response] = asyncio.Queue()
        logger.info(f"SSE connected: {user_type} for session {session_id}")
        return self.message_queues[response]

    async def disconnect(self, response):
        """Disconnect an SSE response from a session."""
        async with self.lock:
            session_id = self.connection_sessions.pop(response, None)
            user_type = self.connection_types.pop(response, None)
            if session_id and session_id in self.active_connections:
                self.active_connections[session_id].discard(response)
                if not self.active_connections[session_id]:
                    del self.active_connections[session_id]
            # Clean up message queue
            if response in self.message_queues:
                del self.message_queues[response]
        logger.info(f"SSE disconnected: {user_type} from session {session_id}")

    async def send_personal_message(self, message: dict, response):
        """Send a message to a specific SSE connection."""
        try:
            if response in self.message_queues:
                await self.message_queues[response].put(message)
        except Exception as e:
            logger.error(f"Error queueing message for SSE: {e}")

    async def broadcast_to_session(self, message: dict, session_id: str, exclude_response=None):
        """Broadcast a message to all SSE connections in a session."""
        async with self.lock:
            connections = self.active_connections.get(session_id, set()).copy()

        if not connections:
            logger.warning(f"No active SSE connections for session {session_id}")
            return

        # Remove excluded connection if specified
        if exclude_response and exclude_response in connections:
            connections.remove(exclude_response)

        if not connections:
            logger.debug(f"No SSE connections to broadcast to after excluding sender")
            return

        # Queue messages to all connections
        for connection in connections:
            if connection in self.message_queues:
                await self.message_queues[connection].put(message)

    async def get_next_message(self, response_or_queue):
        """Get the next message for an SSE connection."""
        queue = response_or_queue
        if not isinstance(response_or_queue, asyncio.Queue):
            queue = self.message_queues.get(response_or_queue)
        
        if queue:
            return await asyncio.wait_for(queue.get(), timeout=30.0)
        return None

    async def get_session_connections(self, session_id: str):
        """Get all active connections for a session."""
        async with self.lock:
            return self.active_connections.get(session_id, set()).copy()

# Global connection manager instance
connection_manager = SSEConnectionManager()
