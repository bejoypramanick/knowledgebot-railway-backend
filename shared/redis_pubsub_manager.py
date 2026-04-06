"""
Redis Pub/Sub Manager for Agent SSE Events
Uses Redis database 3 for real-time event broadcasting
Simplifies SSE architecture by replacing in-memory queues
"""
import redis.asyncio as redis
import json
import logging
from shared.otel_logger import get_otel_logger
from shared.redis_factory import create_async_redis_client
from typing import Dict, Any, Optional, AsyncIterator
import asyncio

logger = get_otel_logger(__name__, "shared")


async def init_pubsub_redis() -> redis.Redis:
    """
    Initialize async Redis client for Pub/Sub on database 3.

    Uses REDIS_URL plus AGENT_EVENTS_REDIS_DB (default 3).

    Returns:
        Async Redis client connected to database 3

    Raises:
        RuntimeError if Redis is not configured
    """
    return await create_async_redis_client(
        primary_env_var="agent_events_pubsub",
        db_env_var="AGENT_EVENTS_REDIS_DB",
        default_db=3,
    )


async def get_pubsub_redis() -> redis.Redis:
    """Get async Redis Pub/Sub client, initializing if needed"""
    return await init_pubsub_redis()


class AgentEventBroadcaster:
    """
    Simplified event broadcaster using Redis Pub/Sub.
    Replaces in-memory event queues with Redis channels.
    Supports both agent channels and session channels (for customers).
    """
    
    def __init__(self):
        self.redis_client = None  # Will be initialized async
    
    async def _ensure_redis(self):
        """Ensure Redis client is initialized"""
        if self.redis_client is None:
            self.redis_client = await get_pubsub_redis()
    
    def _get_agent_channel(self, agent_id: str) -> str:
        """Get Redis channel name for specific agent (uses user ID, not email)"""
        return f"agent:events:{agent_id}"
    
    def _get_broadcast_channel(self) -> str:
        """Get Redis channel name for broadcasting to all agents"""
        return "agent:events:broadcast"
    
    def _get_session_channel(self, session_id: str) -> str:
        """Get Redis channel name for specific session (customer + agent)"""
        return f"session:events:{session_id}"
    
    async def publish_to_agent(self, agent_id: str, event_data: Dict[str, Any]) -> bool:
        """
        Publish event to specific agent's channel.
        
        Args:
            agent_id: Target agent's user ID (from users table)
            event_data: Event data to send
        
        Returns:
            True if published successfully
        """
        try:
            await self._ensure_redis()
            channel = self._get_agent_channel(agent_id)
            message = json.dumps(event_data)
            
            # Publish to Redis channel (async, non-blocking)
            subscribers = await self.redis_client.publish(channel, message)

            if subscribers > 0:
                logger.info(f"📤 Published event to agent {agent_id} on channel {channel}: {event_data.get('type')} ({subscribers} subscribers)")
            else:
                logger.warning(f"📭 No subscribers for agent {agent_id} on channel {channel} - agent may not be connected to SSE")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error publishing to agent {agent_id}: {e}")
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
            await self._ensure_redis()
            channel = self._get_broadcast_channel()
            message = json.dumps(event_data)
            
            subscribers = await self.redis_client.publish(channel, message)
            logger.info(f"📢 Broadcasted event on channel {channel}: {event_data.get('type')} ({subscribers} subscribers)")
            
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
            await self._ensure_redis()
            channel = self._get_session_channel(session_id)
            message = json.dumps(event_data)
            
            # Publish to Redis channel
            subscribers = await self.redis_client.publish(channel, message)

            if subscribers > 0:
                logger.info(f"📤 Published event to session {session_id} on channel {channel}: "
                           f"{event_data.get('type')} ({subscribers} subscribers)")
            else:
                logger.debug(f"📭 No subscribers for session {session_id} on channel {channel}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error publishing to session {session_id}: {e}")
            return False
    
    async def publish_for_session(self, session_id: str, event_data: Dict[str, Any], assigned_agent_id: Optional[str] = None) -> bool:
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
            assigned_agent_id: User ID of assigned agent (if known)
        
        Returns:
            True if published successfully
        """
        try:
            # 1. Publish to session channel (customer + agent receive)
            await self.publish_to_session(session_id, event_data)
            
            # 2. If assigned agent is known, also publish to agent-specific channel
            if assigned_agent_id:
                await self.publish_to_agent(assigned_agent_id, event_data)
            
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
        self.redis_client = None  # Will be initialized async
        self.pubsub = None
    
    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to session's event channel and yield events.
        
        Yields:
            Event data dictionaries
        """
        try:
            # Initialize async Redis client
            self.redis_client = await get_pubsub_redis()
            
            # Create async pubsub instance
            self.pubsub = self.redis_client.pubsub()
            
            # Subscribe to session-specific channel (async, non-blocking)
            session_channel = f"session:events:{self.session_id}"
            await self.pubsub.subscribe(session_channel)

            logger.info(f"🔌 Customer subscribed to channel: {session_channel}")
            
            # Send initial connection event
            yield {
                'type': 'connected',
                'session_id': self.session_id
            }
            
            # Listen for messages using async iteration (non-blocking)
            async for message in self.pubsub.listen():
                try:
                    if message['type'] == 'message':
                        # Parse and yield event data
                        event_data = json.loads(message['data'])
                        yield event_data
                    elif message['type'] == 'subscribe':
                        # Subscription confirmation
                        continue
                    
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
            session_channel = f"session:events:{self.session_id}"
            if self.pubsub:
                try:
                    logger.info(f"🧹 Cleaning up Redis subscription for channel: {session_channel}")
                    await self.pubsub.unsubscribe()
                    logger.info(f"✅ Unsubscribed from channel: {session_channel}")
                except Exception as e:
                    logger.error(f"❌ Error unsubscribing from channel {session_channel}: {e}")
                finally:
                    try:
                        await self.pubsub.close()
                        logger.info(f"🔌 Closed Redis pubsub connection for channel: {session_channel}")
                    except Exception as e:
                        logger.error(f"❌ Error closing Redis pubsub for channel {session_channel}: {e}")
    
    async def unsubscribe(self):
        """Unsubscribe and cleanup"""
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
            logger.info(f"🔌 Customer unsubscribed from session {self.session_id}")


class AgentEventSubscriber:
    """
    Event subscriber for agents using Redis Pub/Sub.
    Replaces asyncio.Queue with Redis subscription.
    Uses user IDs instead of emails for channel names.
    """
    
    def __init__(self, agent_id: str, agent_email: str = None, role: str = 'human_agent'):
        self.agent_id = agent_id
        self.agent_email = agent_email  # For logging only
        self.role = role
        self.redis_client = None  # Will be initialized async
        self.pubsub = None
    
    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        """
        Subscribe to agent's event channel and yield events.
        
        Yields:
            Event data dictionaries
        """
        try:
            # Initialize async Redis client
            self.redis_client = await get_pubsub_redis()
            
            # Create async pubsub instance
            self.pubsub = self.redis_client.pubsub()

            # Subscribe based on role
            if self.role == 'admin':
                # Admins ONLY subscribe to broadcast channel (all chats, view-only if not assigned)
                broadcast_channel = "agent:events:broadcast"
                await self.pubsub.subscribe(broadcast_channel)
                logger.info(f"🔌 Admin {self.agent_email} (ID: {self.agent_id}) subscribed to broadcast channel: {broadcast_channel}")
            else:
                # Human agents subscribe to personal channel (only their assigned chats)
                agent_channel = f"agent:events:{self.agent_id}"
                await self.pubsub.subscribe(agent_channel)
                logger.info(f"🔌 Human agent {self.agent_email} (ID: {self.agent_id}) subscribed to personal channel: {agent_channel}")

            # Send initial connection event
            yield {
                'type': 'connected',
                'agent_id': self.agent_id,
                'agent_email': self.agent_email,
                'role': self.role
            }

            # Listen for messages using async iteration (non-blocking)
            async for message in self.pubsub.listen():
                try:
                    if message['type'] == 'message':
                        # Parse and yield event data
                        logger.info(f"🔌 Agent {self.agent_email} (ID: {self.agent_id}) received Redis message on channel {message.get('channel')}")
                        event_data = json.loads(message['data'])
                        logger.info(f"🔌 Parsed event type: {event_data.get('type')}, yielding to SSE client")
                        yield event_data
                    elif message['type'] == 'subscribe':
                        # Subscription confirmation
                        continue
                    
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
            logger.error(f"❌ Error in subscription for agent {self.agent_id}: {e}")
            raise
        
        finally:
            # Cleanup
            agent_channel = f"agent:events:{self.agent_id}"
            if self.pubsub:
                try:
                    logger.info(f"🧹 Cleaning up Redis subscription for channel: {agent_channel}")
                    await self.pubsub.unsubscribe()
                    logger.info(f"✅ Unsubscribed from channel: {agent_channel}")
                except Exception as e:
                    logger.error(f"❌ Error unsubscribing from channel {agent_channel}: {e}")
                finally:
                    try:
                        await self.pubsub.close()
                        logger.info(f"🔌 Closed Redis pubsub connection for channel: {agent_channel}")
                    except Exception as e:
                        logger.error(f"❌ Error closing Redis pubsub for channel {agent_channel}: {e}")
    
    async def unsubscribe(self):
        """Unsubscribe and cleanup"""
        if self.pubsub:
            await self.pubsub.unsubscribe()
            await self.pubsub.close()
            logger.info(f"🔌 Agent {self.agent_email} (ID: {self.agent_id}) unsubscribed")


# Global broadcaster instance
_broadcaster: Optional[AgentEventBroadcaster] = None


def get_broadcaster() -> AgentEventBroadcaster:
    """Get global broadcaster instance"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = AgentEventBroadcaster()
    return _broadcaster


# Convenience functions
async def broadcast_event_to_agent(agent_id: str, event_data: Dict[str, Any]) -> bool:
    """Broadcast event to specific agent (uses user ID)"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_to_agent(agent_id, event_data)


async def broadcast_event_to_all_agents(event_data: Dict[str, Any]) -> bool:
    """Broadcast event to all agents"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_to_all_agents(event_data)


async def broadcast_event_to_session(session_id: str, event_data: Dict[str, Any]) -> bool:
    """Broadcast event to session channel (customer + agent)"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_to_session(session_id, event_data)


async def broadcast_event_for_session(session_id: str, event_data: Dict[str, Any], assigned_agent_id: Optional[str] = None) -> bool:
    """Broadcast event for specific session (all channels, uses user ID for agent)"""
    broadcaster = get_broadcaster()
    return await broadcaster.publish_for_session(session_id, event_data, assigned_agent_id)
