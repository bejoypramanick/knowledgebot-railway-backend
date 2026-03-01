-- Migration: 007_update_chat_messages_schema.sql
-- Date: 2026-02-28
-- Author: Claude
-- Description: Update chat_messages table schema for read status tracking
-- Purpose: Remove deprecated columns and add is_message_read for tracking read status by human agents/admins

-- ============================================================================
-- OVERVIEW OF CHANGES
-- ============================================================================
-- This migration performs the following operations:
-- 1. Remove deprecated columns that are no longer used
-- 2. Add is_message_read column for tracking message read status
-- 3. Update database indexes for optimal query performance
-- 4. Remove obsolete constraints
--
-- Removed Columns (deprecated):
--   - used_neon_db: No longer tracking Neon DB usage
--   - used_internet_search: Internet search feature deprecated
--   - rating: User ratings moved to separate table/feature
--   - usage_info: Consolidated into other tracking mechanisms
--
-- Added Columns:
--   - is_message_read: Boolean flag (default false) to track if human agent/admin has read the message

-- ============================================================================
-- MIGRATION STEPS
-- ============================================================================

BEGIN TRANSACTION;

-- Step 1: Drop indexes that depend on the columns being removed
-- This prevents constraint violations during column removal
DROP INDEX IF EXISTS idx_chat_messages_rating;

-- Step 2: Remove deprecated columns from chat_messages table
-- Using IF EXISTS to make migration idempotent (safe to run multiple times)
ALTER TABLE public.chat_messages
DROP COLUMN IF EXISTS used_neon_db,
DROP COLUMN IF EXISTS used_internet_search,
DROP COLUMN IF EXISTS rating,
DROP COLUMN IF EXISTS usage_info;

-- Step 3: Drop the rating check constraint since rating column is removed
-- This constraint becomes invalid after column removal
ALTER TABLE public.chat_messages
DROP CONSTRAINT IF EXISTS chat_messages_rating_check;

-- Step 4: Add is_message_read column for read status tracking
-- Default to false (unread) for all messages
-- New messages will default to false until marked as read
ALTER TABLE public.chat_messages
ADD COLUMN IF NOT EXISTS is_message_read BOOLEAN DEFAULT false;

-- Step 5: Create index for efficient queries on read status
-- Improves performance of queries filtering by read status
CREATE INDEX IF NOT EXISTS idx_chat_messages_is_message_read
ON public.chat_messages(is_message_read);

-- Step 6: Create composite index for filtering unread messages by session
-- Optimizes queries that need to find unread messages in a specific session
-- Example: Get count of unread messages in session X
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_unread
ON public.chat_messages(session_id, is_message_read);

-- Step 7: Add column documentation
COMMENT ON COLUMN public.chat_messages.is_message_read IS 'Boolean flag indicating if human agent or admin has marked this message as read. Used for tracking message read status by support staff.';

-- ============================================================================
-- ROLLBACK INSTRUCTIONS (if needed)
-- ============================================================================
-- If this migration needs to be rolled back, execute:
--
-- ALTER TABLE public.chat_messages
--   ADD COLUMN used_neon_db BOOLEAN DEFAULT NULL,
--   ADD COLUMN used_internet_search BOOLEAN DEFAULT NULL,
--   ADD COLUMN rating INT2 DEFAULT NULL,
--   ADD COLUMN usage_info JSONB DEFAULT '{}';
--
-- ALTER TABLE public.chat_messages
--   ADD CONSTRAINT chat_messages_rating_check CHECK (rating >= 1 AND rating <= 5);
--
-- CREATE INDEX idx_chat_messages_rating ON public.chat_messages(rating);
--
-- ALTER TABLE public.chat_messages
--   DROP COLUMN is_message_read;
--
-- DROP INDEX IF EXISTS idx_chat_messages_is_message_read;
-- DROP INDEX IF EXISTS idx_chat_messages_session_unread;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- After running this migration, verify the changes with:
--
-- 1. Check that deprecated columns are removed:
--    SELECT column_name FROM information_schema.columns
--    WHERE table_name='chat_messages' AND column_name IN ('used_neon_db', 'used_internet_search', 'rating', 'usage_info');
--    (Should return 0 rows)
--
-- 2. Check that is_message_read column exists:
--    SELECT column_name, data_type, is_nullable, column_default
--    FROM information_schema.columns
--    WHERE table_name='chat_messages' AND column_name='is_message_read';
--    (Should show: is_message_read, boolean, NO, false)
--
-- 3. Check that new indexes exist:
--    SELECT indexname FROM pg_indexes
--    WHERE tablename='chat_messages' AND indexname IN ('idx_chat_messages_is_message_read', 'idx_chat_messages_session_unread');
--    (Should return 2 rows)

COMMIT;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
-- This migration successfully updates the chat_messages table schema.
-- The system is now ready to track message read status for human agents and admins.
