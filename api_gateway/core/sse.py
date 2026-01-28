import asyncio
import json
import logging
from typing import List

logger = logging.getLogger(__name__)

class SSEConnectionManager:
    """Manages SSE connections for real-time communication."""
    
    def __init__(self):
        self.active_connections: List[asyncio.Queue] = []
        self.lock = asyncio.Lock()
    
    async def connect(self):
        """Connect a new SSE client."""
        queue = asyncio.Queue()
        async with self.lock:
            self.active_connections.append(queue)
        return queue
    
    async def disconnect(self, queue: asyncio.Queue):
        """Disconnect an SSE client."""
        async with self.lock:
            if queue in self.active_connections:
                self.active_connections.remove(queue)
    
    async def broadcast(self, message: dict):
        """Broadcast a message to all connected SSE clients."""
        if not self.active_connections:
            return
        
        message_str = f"data: {json.dumps(message)}\n\n"
        disconnected = []
        
        for queue in self.active_connections:
            try:
                await queue.put(message_str)
            except Exception as e:
                logger.error(f"Error broadcasting to SSE client: {e}")
                disconnected.append(queue)
        
        # Clean up disconnected queues
        if disconnected:
            async with self.lock:
                for queue in disconnected:
                    if queue in self.active_connections:
                        self.active_connections.remove(queue)

# Global SSE connection manager
sse_manager = SSEConnectionManager()

async def sse_generator(queue: asyncio.Queue):
    """Generate SSE events for a client."""
    try:
        while True:
            try:
                # Wait for a message with timeout
                message = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield message
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                yield "data: {\"type\": \"ping\"}\n\n"
    except asyncio.CancelledError:
        # Client disconnected
        pass
