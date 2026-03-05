"""
Redis Pub/Sub Manager for Agent SSE Events
Uses Redis database 4 for real-time event broadcasting
Simplifies SSE architecture by replacing in-memory queues
"""
import redis
import json
import logging
import os
from typing import Dict, Any, Optional, AsyncIterator
import asyncio

logger = logging.getLogger(__name__)

# Global Redis client for Pub/Sub (database 4)
_pubsub_redis_client: Optional[redis.Redis] = None


def init_pubsub_redis() -> redis.Redis:
    """
    Initialize Redis client for Pub/Sub on database 4.
    
    Databases in use:
    - 0: Celery tasks
    - 1: Web crawling queue
    - 2: File processing
    - 3: Session storage
    - 4: Agent SSE Pub/Sub (NEW)
    
    Returns:
        Redis client connected to database 4
    
    Raises:
        RuntimeError if Redis is not configured
    """
    global _pubsub_redis_client
    
    if _pubsub_redis_client is not None:
        return _pubsub_redis_client
    
    redis_url = os.getenv('REDIS_URL')
    
    if not redis_url:
        raise RuntimeError(
            "REDIS_URL environment variable not set. "
            "Redis Pub/Sub is required for agent SSE events."
        )
    
    try:
        logger.info(f"🔌 Initializing Redis Pub/Sub client (database 4)...")
        
        # Always use database 4 for Pub/Sub
        if redis_url.endswith(('/0', '/1', '/2', '/3')):
            # Remove existing database number
            redis_url = redis_url.rsplit('/', 1)[0]
        
        _pubsub_redis_client = redis.from_url(
            redis_url,
            db=4,  # Use database 4 for Pub/Sub
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30
        )
        
        # Test connection
        _pubsub_redis_client.ping()
        logger.info("✅ Redis Pub/Sub client initialized successfully (db=4)")
        
        return _pubsub_redis_client
        
    except redis.ConnectionError as e:
        logger.error(f"❌ Failed to connect to Redis for Pub/Sub: {e}")
        raise RuntimeError(f"Redis Pub/Sub connection failed: {e}")


def get_pubsub_redis() -> redis.Redis:
    """Get Redis Pub/Sub client, initializing if needed"""
    if _pubsub_redis_client is None:
        return init_pubsub_redis()
    return _pubsub_redis_client


class AgentEventBroadcaster:
    """
    Simplified event broadcaster using Redis Pub/Sub.
    Replaces in-memory event queues with Redis channels.
    Supports both agent channels and session channels (for customers).
    """
    
    def __init__(self):
        self.redis_client = get_pubsub_redis()
    
    def _get_agent_channel(self, agent_email: str) -> str:
        """Get Redis channel name for specific agent"""
        return f"agent:events:{agent_email}"
    
    def _get_broadcast_channel(self) -> str:
        """Get Redis channel name for broadcasting to all agents"""
        return "agent:events:broadcast"
    
    def _get_session_channel(self, session_id: str) -> str:
        """Get Redis channel name for specific session (customer + agent)"""
        return f"session:events:{session_id}"
    
    async def publish_to_agent(self, agent_email: str, event_data: Dict[str, Any]) -> bool:
        """
        Publish event to specific agent's channel.
        
        Args:
            agent_email: Target agent's email
            event_data: Event data to send
        
        Returns:
            True if published successfully
        """
        try:
            channel = self._get_agent_channel(agent_email)
            message = json.dumps(event_data)
            
            # Publish to Redis channel (non-blocking)
            subscribers = self.redis_client.publish(channel, message)
            
            if subscribers > 0:
                logger.info(f"📤 Published event to {agent_email}: {event_data.get('type')} ({subscribers} subscribers)")
            else:
                logger.debug(f"📭 No subscribers for {agent_email}, event queued in Redis")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error publishing to {agent_email}: {e}")
            return False
    
    async def publish_to_all_agents(self, event_data: Dict[str, Any]) -> bool:
        """
        Broadcast event to all connected agents.
        
        Args:
            event_data: Event data to send
        
        Returns:
            True if published successfully
        """
        try:
            channel = self._get_broadcast_channel()
            message = json.dumps(event_data)
            
            subscribers = self.redis_client.publish(channel, message)
            logger.info(f"📢 Broadcasted event to all agents: {event_data.get('type')} ({subscribers} subscribers)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error broadcasting to all agents: {e}")
            return False
    
    async def publish_to_session(self, session_id: str, event_data: Dict[str, Any]) -> bool:
        """
        Publish event to session channel (customer + agent receive).
        
        Args:
            session_id: Session ID
            event_data: Event data to send
        
        Returns:
            True if published successfully
        """
        try:
            channel = self._get_session_channel(session_id)
            message = json.dumps(event_data)
            
            # Publish to Redis channel
            subscribers = self.redis_client.publish(channel, message)
            
            if subscribers > 0:
                logger.info(f"📤 Published event to session {session_id}: "
                           f"{event_data.get('type')} ({subscribers} subscribers)")
            else:
                logger.debug(f"📭 No subscribers for session {session_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error publishing to session {session_id}: {e}")
            return False
    
    async def publish_for_session(self, session_id: str, event_data: Dict[str, Any], assigned_agent: Optional[str] = None) -> bool:
        """
        Publish event to all relevant channels for a session.
        
        DEPRECATED: Use specific broadcast functions instead for better control:
        - broadcast_event_to_session() for customer messages
        - broadcast_event_to_agent() for agent-specific messages
        - broadcast_event_to_all_agents() for admin broadcasts
        
        This method publishes to ALL channels (wasteful):
        1. Session channel (customer + agent)
        2. Agent-specific channel (agent only)
        3. Broadcast channel (admins)
        
        Args:
            session_id: Session ID
            event_data: Event data to send
            assigned_agent: Email of assigned agent (if known)
        
        Returns:
            True if published successfully
        """
        try:
            # 1. Publish to session channel (customer + agent receive)
            await self.publish_to_session(session_id, event_data)
            
            # 2. If assigned agent is known, also publish to agent-specific channel
            if assigned_agent:
                await self.publish_to_agent(assigned_agent, event_data)
            
            # 3. Always broadcast to admins (they see all sessions)
            await self.publish_to_all_agents(event_data)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error publishing for session {session_id}: {e}")
            return False




class SessionEventSubscriber:
    """
    Event subscriber for customers using session-based channels.
    No authentication required - uses session ID only.
    Perfect for anonymous customer chat widgets.
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.redis_client = get_pubsub_redis()
        self.pubsub = None
    
    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to session's event channel and yield events.
        
        Yields:
            Event data dictionaries
        """
        try:
            # Create pubsub instance
            self.pubsub = self.redis_client.pubsub()
            
            # Subscribe to session-specific channel
            session_channel = f"session:events:{self.session_id}"
            self.pubsub.subscribe(session_channel)
            
            logger.info(f"🔌 Customer subscribed to session {self.session_id}")
            
            # Send initial connection event
            yield {
                'type': 'connected',
                'session_id': self.session_id
            }
            
            # Listen for messages
            while True:
                try:
                    # Get message with timeout (for heartbeat)
                    message = self.pubsub.get_message(timeout=30.0)
                    
                    if message and message['type'] == 'message':
                        # Parse and yield event data
                        event_data = json.loads(message['data'])
                        yield event_data
                    
                    elif message is None:
                        # Timeout - send heartbeat
                        yield {'type': 'ping'}
                    
                    # Small sleep to prevent busy loop
                    await asyncio.sleep(0.1)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Invalid JSON in Redis message: {e}")
                    continue
                    
                except Exception as e:
                    logger.error(f"❌ Error receiving message: {e}")
                    # Send error event but continue listening
                    yield {
                        'type': 'error',
                        'message': str(e)
                    }
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"❌ Error in subscription for session {self.session_id}: {e}")
            raise
        
        finally:
            # Cleanup
            if self.pubsub:
                self.pubsub.unsubscribe()
                self.pubsub.close()
                logger.info(f"🔌 Customer unsubscribed from session {self.session_id}")
    
    async def unsubscribe(self):
        """Unsubscribe and cleanup"""
        if self.pubsub:
            self.pubsub.unsubscribe()
            self.pubsub.close()
            logger.info(f"🔌 Customer unsubscribed from session {self.session_id}")


class AgentEventSubscriber:
    """
    Event subscriber for agents using Redis Pub/Sub.
    Replaces asyncio.Queue with Redis subscription.
    """
    
    def __init__(self, agent_email: str, role: str = 'human_agent'):
        self.agent_email = agent_email
        self.role = role
        self.redis_client = get_pubsub_redis()
        self.pubsub = None
    
    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to agent's event channel and yield events.
        
        Yields:
            Event data dictionaries
        """
        try:
            # Create pubsub instance
            self.pubsub = self.redis_client.pubsub()
            
            # Subscribe to agent-specific channel
            agent_channel = f"agent:events:{self.agent_email}"
            self.pubsub.subscribe(agent_channel)
            
            # Admins also subscribe to broadcast channel
            if self.role == 'admin':
                broadcast_channel = "agent:events:broadcast"
                self.pubsub.subscribe(broadcast_channel)
                logger.info(f"🔌 Admin {self.agent_email} subscribed to broadcast channel")
            
            logger.info(f"🔌 Agent {self.agent_email} subscribed to Redis Pub/Sub")
            
            # Send initial connection event
            yield {
                'type': 'connected',
                'agent_email': self.agent_email,
                'role': self.role
            }
            
            # Listen for messages
            while True:
                try:
                    # Get message with timeout (for heartbeat)
                    message = self.pubsub.get_message(timeout=30.0)
                    
                    if message and message['type'] == 'message':
                        # Parse and yield event data
                        event_data = json.loads(message['data'])
                        yield event_data
                    
                    elif message is None:
                        # Timeout - send heartbeat
                        yield {'type': 'ping'}
                    
                    # Small sleep to prevent busy loop
                    await asyncio.sleep(0.1)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Invalid JSON in Redis message: {e}")
                    continue
                    
                except Exception as e:
                    logger.error(f"❌ Error receiving message: {e}")
                    # Send error event but continue listening
                    yield {
                        'type': 'error',
                        'message': str(e)
                    }
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"❌ Error in subscription for {self.agent_email}: {e}")
            raise
        
        finally:
            # Cleanup
            if self.pubsub:
                self.pubsub.unsubscribe()
                self.pubsub.close()
                logger.info(f"🔌 Agent {self.agent_email} unsubscribed from Redis Pub/Sub")
    
    async def unsubscribe(self):
        """Unsubscribe and cleanup"""
        if self.pubsub:
            self.pubsub.unsubscribe()
            self.pubsub.close()
            logger.info(f"🔌 Agent {self.agent_email} unsubscribed")


# Global broadcaster instance
_broadcaster: Optional[AgentEventBroadcaster] = None


def get_broadcaster() -> AgentEventBroadcaster:
    """Get global broadcaster instance"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = AgentEventBroadcaster()
    return _broadcaster


# Convenience functions for backward compatibility
async def broadcast_event_to_agent(agent_email: str, event_data: Dict[str, Any]) -> bool:
    """Broadcast event to specific agent"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_to_agent(agent_email, event_data)


async def broadcast_event_to_all_agents(event_data: Dict[str, Any]) -> bool:
    """Broadcast event to all agents"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_to_all_agents(event_data)


async def broadcast_event_to_session(session_id: str, event_data: Dict[str, Any]) -> bool:
    """Broadcast event to session channel (customer + agent)"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_to_session(session_id, event_data)


async def broadcast_event_for_session(session_id: str, event_data: Dict[str, Any], assigned_agent: Optional[str] = None) -> bool:
    """Broadcast event for specific session (all channels)"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_for_session(session_id, event_data, assigned_agent)
