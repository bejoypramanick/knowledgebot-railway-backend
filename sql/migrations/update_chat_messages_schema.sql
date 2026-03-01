-- Migration: Update chat_messages table schema
-- Description: Remove deprecated columns and add is_message_read column
-- Purpose: Clean up unused columns (used_neon_db, used_internet_search, rating, usage_info)
--          and add is_message_read for tracking read status by human agents/admins

-- Drop indexes that depend on the columns being removed
DROP INDEX IF EXISTS idx_chat_messages_rating;

-- Remove columns
ALTER TABLE public.chat_messages
DROP COLUMN IF EXISTS used_neon_db,
DROP COLUMN IF EXISTS used_internet_search,
DROP COLUMN IF EXISTS rating,
DROP COLUMN IF EXISTS usage_info;

-- Drop the rating check constraint since rating column is removed
ALTER TABLE public.chat_messages
DROP CONSTRAINT IF EXISTS chat_messages_rating_check;

-- Add is_message_read column to track if human agent/admin has read the message
ALTER TABLE public.chat_messages
ADD COLUMN IF NOT EXISTS is_message_read BOOLEAN DEFAULT false;

-- Create index for efficient queries on read status
CREATE INDEX IF NOT EXISTS idx_chat_messages_is_message_read
ON public.chat_messages(is_message_read);

-- Create index for filtering unread messages by session
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_unread
ON public.chat_messages(session_id, is_message_read);

COMMENT ON COLUMN public.chat_messages.is_message_read IS 'Tracks if human agent or admin has marked this message as read';
