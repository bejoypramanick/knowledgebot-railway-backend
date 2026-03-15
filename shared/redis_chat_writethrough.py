"""
Redis Chat Write-Through Service
Background asyncio task that periodically flushes dirty chat sessions
from Redis (DB 6) to PostgreSQL for durable archival.

Runs inside chatbot_orchestration's event loop.
Configurable via:
  CHAT_WRITETHROUGH_INTERVAL=5  (seconds between flush cycles)
  CHAT_WRITETHROUGH_BATCH_SIZE=50  (max messages per batch INSERT)
"""
import asyncio
import os
from typing import Optional

from shared.otel_logger import get_otel_logger
from shared.redis_chat_store import get_chat_store, RedisChatStore

logger = get_otel_logger(__name__, "shared")


class ChatWriteThroughService:
    """
    Background service that flushes Redis chat data to PostgreSQL.

    Flush cycle (every N seconds):
    1. SMEMBERS chat:dirty_sessions -> get dirty session UUIDs
    2. For each session:
       a. Ensure session row exists in PG (INSERT ... ON CONFLICT DO NOTHING)
       b. Get unsynced messages from Redis (after sync_index)
       c. Batch INSERT INTO chat_messages
       d. UPDATE chat_sessions SET message_count, last_activity_at
       e. Update sync_index in Redis
       f. If fully synced, SREM from dirty set
    """

    _instance: Optional['ChatWriteThroughService'] = None

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._interval = int(os.getenv('CHAT_WRITETHROUGH_INTERVAL', '5'))
        self._batch_size = int(os.getenv('CHAT_WRITETHROUGH_BATCH_SIZE', '50'))
        self._store: RedisChatStore = get_chat_store()

    @classmethod
    def get_instance(cls) -> 'ChatWriteThroughService':
        if cls._instance is None:
            cls._instance = ChatWriteThroughService()
        return cls._instance

    async def start(self):
        """Start the background write-through task."""
        if self._running:
            logger.warning("Write-through service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Write-through service started (interval={self._interval}s, batch={self._batch_size})")

    async def stop(self):
        """Stop the background task gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Write-through service stopped")

    async def _run_loop(self):
        """Main loop: flush dirty sessions every interval."""
        while self._running:
            try:
                await self._flush_cycle()
            except Exception as e:
                logger.error(f"Write-through flush cycle error: {e}", exc_info=True)

            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _flush_cycle(self):
        """One flush cycle: process all dirty sessions."""
        dirty_sessions = await self._store.get_dirty_sessions()
        if not dirty_sessions:
            return

        logger.debug(f"Write-through: {len(dirty_sessions)} dirty sessions to flush")

        for session_uuid in dirty_sessions:
            try:
                await self._flush_session(session_uuid)
            except Exception as e:
                logger.error(f"Write-through flush failed for {session_uuid}: {e}")
                # Leave in dirty set for retry next cycle

    async def _flush_session(self, session_uuid: str):
        """Flush one session's data to PostgreSQL."""
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        # Get session data from Redis
        session_data = await self._store.get_session(session_uuid)
        if not session_data:
            # Session expired from Redis - remove from dirty set
            await self._store.remove_from_dirty(session_uuid)
            return

        # Get unsynced messages
        unsynced = await self._store.get_unsynced_messages(session_uuid)
        if not unsynced and session_data.get("pg_synced"):
            # Nothing to sync
            await self._store.remove_from_dirty(session_uuid)
            return

        try:
            async with get_db_session() as db:
                # Step 1: Ensure session row exists in PG
                db_id = session_data.get("db_id")
                if not db_id:
                    # INSERT with ON CONFLICT for idempotency
                    result = await db.execute(
                        text("""
                            INSERT INTO chat_sessions (session_id, is_active, archive_status, started_at, last_activity_at, message_count)
                            VALUES (:session_uuid, true, 'active', :started_at, :last_activity_at, 0)
                            ON CONFLICT (session_id) DO UPDATE SET last_activity_at = EXCLUDED.last_activity_at
                            RETURNING id
                        """),
                        {
                            "session_uuid": session_uuid,
                            "started_at": session_data.get("started_at"),
                            "last_activity_at": session_data.get("last_activity_at")
                        }
                    )
                    db_id = result.scalar()
                    await db.commit()

                    # Cache the db_id back in Redis
                    await self._store.set_session_db_id(session_uuid, db_id)
                    logger.info(f"Write-through: PG session ensured {session_uuid} -> DB ID {db_id}")

                # Step 2: Batch insert unsynced messages
                if unsynced:
                    batch = unsynced[:self._batch_size]
                    max_index = 0

                    for msg in batch:
                        await db.execute(
                            text("""
                                INSERT INTO chat_messages (session_id, role, content, created_at, updated_at)
                                VALUES (:session_id, :role, :content, :created_at, NOW())
                            """),
                            {
                                "session_id": db_id,
                                "role": msg["role"],
                                "content": msg["content"],
                                "created_at": msg.get("created_at")
                            }
                        )
                        max_index = msg.get("_index", max_index)

                    # Step 3: Update session metadata
                    await db.execute(
                        text("""
                            UPDATE chat_sessions
                            SET message_count = (SELECT COUNT(*) FROM chat_messages WHERE session_id = :db_id),
                                last_activity_at = :last_activity,
                                updated_at = NOW()
                            WHERE id = :db_id
                        """),
                        {
                            "db_id": db_id,
                            "last_activity": session_data.get("last_activity_at")
                        }
                    )

                    await db.commit()

                    # Step 4: Update sync index in Redis
                    # +1 because sync_index represents "flush from this index onwards"
                    await self._store.mark_synced(session_uuid, max_index + 1)

                    logger.info(f"Write-through: flushed {len(batch)} messages for {session_uuid} (up to index {max_index})")

                    # If we flushed all unsynced, remove from dirty
                    if len(batch) >= len(unsynced):
                        await self._store.remove_from_dirty(session_uuid)
                else:
                    # No messages to sync, just update session metadata
                    await db.execute(
                        text("""
                            UPDATE chat_sessions
                            SET last_activity_at = :last_activity, updated_at = NOW()
                            WHERE id = :db_id
                        """),
                        {
                            "db_id": db_id,
                            "last_activity": session_data.get("last_activity_at")
                        }
                    )
                    await db.commit()
                    await self._store.remove_from_dirty(session_uuid)

        except Exception as e:
            logger.error(f"Write-through PG flush failed for {session_uuid}: {e}")
            # Leave in dirty set - retry next cycle

    async def flush_now(self, session_uuid: str):
        """Immediately flush a specific session (e.g., on session close)."""
        try:
            await self._flush_session(session_uuid)
            logger.info(f"Write-through: immediate flush completed for {session_uuid}")
        except Exception as e:
            logger.error(f"Write-through immediate flush failed for {session_uuid}: {e}")

    async def flush_all(self):
        """Flush all dirty sessions (called on graceful shutdown)."""
        dirty = await self._store.get_dirty_sessions()
        if dirty:
            logger.info(f"Write-through: flushing {len(dirty)} sessions on shutdown...")
            for session_uuid in dirty:
                try:
                    await self._flush_session(session_uuid)
                except Exception as e:
                    logger.error(f"Write-through shutdown flush failed for {session_uuid}: {e}")
            logger.info("Write-through: shutdown flush completed")

    async def recovery_sync(self):
        """
        Recovery on startup: flush any leftover dirty sessions from previous run.
        Called after service initialization.
        """
        try:
            dirty = await self._store.get_dirty_sessions()
            if dirty:
                logger.info(f"Write-through: recovery sync - {len(dirty)} dirty sessions from previous run")
                for session_uuid in dirty:
                    try:
                        await self._flush_session(session_uuid)
                    except Exception as e:
                        logger.error(f"Write-through recovery flush failed for {session_uuid}: {e}")
                logger.info("Write-through: recovery sync completed")
            else:
                logger.info("Write-through: no dirty sessions to recover")
        except Exception as e:
            logger.error(f"Write-through recovery_sync error: {e}")

    async def get_pending_count(self) -> int:
        """Get number of dirty sessions pending flush."""
        try:
            dirty = await self._store.get_dirty_sessions()
            return len(dirty)
        except Exception:
            return 0
