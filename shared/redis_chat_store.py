"""
Redis Chat Store (DB 6)
Primary storage for hot-path chat sessions and messages.
PostgreSQL becomes a durable archive via async write-through.
The SSE streaming path touches zero PostgreSQL connections after first message.

Env var: CHAT_STORE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/6

Redis Data Model:
  Session (Hash):   chat:session:{session_uuid}  -> session_uuid, user_role_id, started_at, ...
  Messages (List):  chat:messages:{session_uuid}  -> JSON objects appended via RPUSH
  Dirty Set:        chat:dirty_sessions           -> SET of session_uuids needing PG flush
  Sync Index:       chat:sync_index:{session_uuid} -> index of last synced message
"""
import redis.asyncio as redis
import json
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "shared")

# Global Redis client for chat store (database 6)
_chat_store_client: Optional[redis.Redis] = None

# Key patterns
SESSION_KEY = "chat:session:{}"
MESSAGES_KEY = "chat:messages:{}"
DIRTY_SET_KEY = "chat:dirty_sessions"
SYNC_INDEX_KEY = "chat:sync_index:{}"

# TTLs
SESSION_TTL = 86400  # 24 hours
MESSAGES_TTL = 86400  # 24 hours


async def init_chat_store_redis() -> redis.Redis:
    """
    Initialize async Redis client for chat store on database 6.

    Requires CHAT_STORE_REDIS_URL environment variable.
    Format: redis://default:<password>@redis.railway.internal:6379/6
    """
    global _chat_store_client

    if _chat_store_client is not None:
        return _chat_store_client

    redis_url = os.getenv('CHAT_STORE_REDIS_URL')

    if not redis_url:
        pubsub_url = os.getenv('PUBSUB_REDIS_URL', '')
        if pubsub_url:
            if '/' in pubsub_url.rsplit(':', 1)[-1]:
                redis_url = pubsub_url.rsplit('/', 1)[0] + '/6'
            else:
                redis_url = pubsub_url + '/6'
            logger.info("Derived CHAT_STORE_REDIS_URL from PUBSUB_REDIS_URL (DB 6)")
        else:
            raise RuntimeError(
                "CHAT_STORE_REDIS_URL environment variable not set. "
                "Format: redis://default:<password>@redis.railway.internal:6379/6"
            )

    try:
        logger.info("Initializing Redis chat store client (database 6)...")

        _chat_store_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30
        )

        await _chat_store_client.ping()
        logger.info("Redis chat store client initialized (db=6)")

        return _chat_store_client

    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis chat store: {e}")
        raise RuntimeError(f"Redis chat store connection failed: {e}")


async def get_chat_store_redis() -> redis.Redis:
    """Get async Redis chat store client, initializing if needed."""
    if _chat_store_client is None:
        return await init_chat_store_redis()
    return _chat_store_client


class RedisChatStore:
    """
    Redis-backed chat session and message store.
    Provides atomic operations via Redis pipelines.
    All ops are try/except wrapped - callers should fall back to PG on failure.
    """

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def _ensure_client(self):
        if self._client is None:
            self._client = await get_chat_store_redis()

    # ─── Session Operations ───────────────────────────────────────────

    async def get_or_create_session(
        self,
        session_uuid: str,
        user_role_id: str = None,
        metadata: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get existing session from Redis or create a new one.
        Does NOT create the PG row - that happens on first message via write-through
        or via a single INSERT when numeric ID is needed.

        Returns:
            Session dict or None on failure
        """
        try:
            await self._ensure_client()
            session_key = SESSION_KEY.format(session_uuid)

            # Check if session already exists in Redis
            existing = await self._client.hgetall(session_key)
            if existing:
                logger.debug(f"Redis session HIT: {session_uuid}")
                return self._deserialize_session(existing)

            # Create new session in Redis
            # PG18: session_uuid IS the UUIDv7 PK — no separate db_id needed
            now = datetime.now(timezone.utc).isoformat()
            session_data = {
                "session_uuid": session_uuid,
                "user_role_id": user_role_id if user_role_id else "",
                "started_at": now,
                "last_activity_at": now,
                "is_active": "true",
                "message_count": "0",
                "metadata": json.dumps(metadata or {}),
                "archive_status": "active",
                "pg_synced": "false"
            }

            pipe = self._client.pipeline()
            pipe.hset(session_key, mapping=session_data)
            pipe.expire(session_key, SESSION_TTL)
            await pipe.execute()

            logger.info(f"Redis session CREATED: {session_uuid}")
            return self._deserialize_session(session_data)

        except Exception as e:
            logger.warning(f"Redis get_or_create_session failed for {session_uuid}: {e}")
            return None

    async def get_session(self, session_uuid: str) -> Optional[Dict[str, Any]]:
        """Get session data from Redis."""
        try:
            await self._ensure_client()
            session_key = SESSION_KEY.format(session_uuid)
            data = await self._client.hgetall(session_key)
            if data:
                return self._deserialize_session(data)
            return None
        except Exception as e:
            logger.warning(f"Redis get_session failed for {session_uuid}: {e}")
            return None

    async def update_session_activity(self, session_uuid: str) -> bool:
        """Update last_activity_at timestamp."""
        try:
            await self._ensure_client()
            session_key = SESSION_KEY.format(session_uuid)
            now = datetime.now(timezone.utc).isoformat()
            await self._client.hset(session_key, "last_activity_at", now)
            return True
        except Exception as e:
            logger.warning(f"Redis update_session_activity failed: {e}")
            return False

    async def close_session(self, session_uuid: str) -> bool:
        """Mark session as closed in Redis."""
        try:
            await self._ensure_client()
            session_key = SESSION_KEY.format(session_uuid)
            now = datetime.now(timezone.utc).isoformat()
            pipe = self._client.pipeline()
            pipe.hset(session_key, mapping={
                "is_active": "false",
                "archive_status": "closed",
                "last_activity_at": now
            })
            await pipe.execute()
            logger.info(f"Redis session CLOSED: {session_uuid}")
            return True
        except Exception as e:
            logger.warning(f"Redis close_session failed: {e}")
            return False

    # ─── Message Operations ───────────────────────────────────────────

    async def save_message(
        self,
        session_uuid: str,
        role: str,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Save a message to Redis. Uses a pipeline for atomic:
        1. RPUSH message to list
        2. HINCRBY message_count
        3. HSET last_activity_at
        4. SADD to dirty_sessions

        Returns:
            Message dict or None on failure
        """
        try:
            await self._ensure_client()

            now = datetime.now(timezone.utc).isoformat()
            message = {
                "role": role,
                "content": content,
                "created_at": now,
                "metadata": metadata or {},
                "pg_synced": False
            }
            message_json = json.dumps(message)

            session_key = SESSION_KEY.format(session_uuid)
            messages_key = MESSAGES_KEY.format(session_uuid)

            pipe = self._client.pipeline()
            pipe.rpush(messages_key, message_json)
            pipe.hincrby(session_key, "message_count", 1)
            pipe.hset(session_key, "last_activity_at", now)
            pipe.sadd(DIRTY_SET_KEY, session_uuid)
            pipe.expire(messages_key, MESSAGES_TTL)
            pipe.expire(session_key, SESSION_TTL)
            results = await pipe.execute()

            # results[0] is the new list length (= index + 1)
            message_index = results[0] - 1

            logger.debug(f"Redis message SAVED: {session_uuid} [{role}] index={message_index}")

            return {
                "index": message_index,
                "role": role,
                "content": content,
                "created_at": now,
                "session_uuid": session_uuid
            }

        except Exception as e:
            logger.warning(f"Redis save_message failed for {session_uuid}: {e}")
            return None

    async def get_messages(self, session_uuid: str) -> List[Dict[str, Any]]:
        """Get all messages for a session from Redis."""
        try:
            await self._ensure_client()
            messages_key = MESSAGES_KEY.format(session_uuid)
            raw_messages = await self._client.lrange(messages_key, 0, -1)

            messages = []
            for raw in raw_messages:
                try:
                    msg = json.loads(raw)
                    messages.append(msg)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in Redis message list for {session_uuid}")
                    continue

            logger.debug(f"Redis messages GET: {session_uuid} -> {len(messages)} messages")
            return messages

        except Exception as e:
            logger.warning(f"Redis get_messages failed for {session_uuid}: {e}")
            return []

    async def get_message_count(self, session_uuid: str) -> int:
        """Get message count from Redis."""
        try:
            await self._ensure_client()
            messages_key = MESSAGES_KEY.format(session_uuid)
            count = await self._client.llen(messages_key)
            return count
        except Exception as e:
            logger.warning(f"Redis get_message_count failed: {e}")
            return 0

    # ─── Write-Through Support ────────────────────────────────────────

    async def mark_dirty(self, session_uuid: str) -> bool:
        """Mark a session as needing PG flush."""
        try:
            await self._ensure_client()
            await self._client.sadd(DIRTY_SET_KEY, session_uuid)
            return True
        except Exception as e:
            logger.warning(f"Redis mark_dirty failed: {e}")
            return False

    async def get_dirty_sessions(self) -> Set[str]:
        """Get all session UUIDs that need PG flush."""
        try:
            await self._ensure_client()
            members = await self._client.smembers(DIRTY_SET_KEY)
            return members
        except Exception as e:
            logger.warning(f"Redis get_dirty_sessions failed: {e}")
            return set()

    async def get_unsynced_messages(self, session_uuid: str) -> List[Dict[str, Any]]:
        """Get messages that haven't been synced to PG yet."""
        try:
            await self._ensure_client()
            sync_index_key = SYNC_INDEX_KEY.format(session_uuid)
            messages_key = MESSAGES_KEY.format(session_uuid)

            # Get sync index (how far we've flushed)
            sync_index_str = await self._client.get(sync_index_key)
            sync_index = int(sync_index_str) if sync_index_str else 0

            # Get messages after sync_index
            raw_messages = await self._client.lrange(messages_key, sync_index, -1)

            messages = []
            for i, raw in enumerate(raw_messages):
                try:
                    msg = json.loads(raw)
                    msg["_index"] = sync_index + i
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue

            return messages

        except Exception as e:
            logger.warning(f"Redis get_unsynced_messages failed for {session_uuid}: {e}")
            return []

    async def mark_synced(self, session_uuid: str, up_to_index: int) -> bool:
        """Update sync index after successful PG flush."""
        try:
            await self._ensure_client()
            sync_index_key = SYNC_INDEX_KEY.format(session_uuid)
            await self._client.set(sync_index_key, str(up_to_index))
            logger.debug(f"Redis sync_index updated: {session_uuid} -> {up_to_index}")
            return True
        except Exception as e:
            logger.warning(f"Redis mark_synced failed: {e}")
            return False

    async def remove_from_dirty(self, session_uuid: str) -> bool:
        """Remove session from dirty set after full sync."""
        try:
            await self._ensure_client()
            await self._client.srem(DIRTY_SET_KEY, session_uuid)
            return True
        except Exception as e:
            logger.warning(f"Redis remove_from_dirty failed: {e}")
            return False

    async def delete_session(self, session_uuid: str) -> bool:
        """Delete session and messages from Redis."""
        try:
            await self._ensure_client()
            session_key = SESSION_KEY.format(session_uuid)
            messages_key = MESSAGES_KEY.format(session_uuid)
            sync_index_key = SYNC_INDEX_KEY.format(session_uuid)

            pipe = self._client.pipeline()
            pipe.delete(session_key)
            pipe.delete(messages_key)
            pipe.delete(sync_index_key)
            pipe.srem(DIRTY_SET_KEY, session_uuid)
            await pipe.execute()

            logger.info(f"Redis session DELETED: {session_uuid}")
            return True
        except Exception as e:
            logger.warning(f"Redis delete_session failed: {e}")
            return False

    # ─── Helpers ──────────────────────────────────────────────────────

    def _deserialize_session(self, data: Dict[str, str]) -> Dict[str, Any]:
        """Convert Redis hash string values to proper types."""
        return {
            "session_uuid": data.get("session_uuid", ""),
            "user_role_id": data["user_role_id"] if data.get("user_role_id") else None,
            "started_at": data.get("started_at"),
            "last_activity_at": data.get("last_activity_at"),
            "is_active": data.get("is_active", "true") == "true",
            "message_count": int(data.get("message_count", "0")),
            "metadata": json.loads(data.get("metadata", "{}")) if data.get("metadata") else {},
            "archive_status": data.get("archive_status", "active"),
            "pg_synced": data.get("pg_synced", "false") == "true"
        }


# Global singleton
_chat_store: Optional[RedisChatStore] = None


def get_chat_store() -> RedisChatStore:
    """Get global RedisChatStore singleton."""
    global _chat_store
    if _chat_store is None:
        _chat_store = RedisChatStore()
    return _chat_store
