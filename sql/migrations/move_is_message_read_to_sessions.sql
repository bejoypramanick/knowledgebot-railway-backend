-- Migration: Move is_message_read from chat_messages to chat_sessions
-- Purpose: Track read status at session level, not per-message

BEGIN TRANSACTION;

-- Step 1: Remove is_message_read column from chat_messages
DROP INDEX IF EXISTS idx_chat_messages_is_message_read;
DROP INDEX IF EXISTS idx_chat_messages_session_unread;

ALTER TABLE public.chat_messages
DROP COLUMN IF EXISTS is_message_read;

-- Step 2: Add is_session_read to chat_sessions
ALTER TABLE public.chat_sessions
ADD COLUMN IF NOT EXISTS is_session_read BOOLEAN DEFAULT false;

-- Step 3: Create index for efficient queries
CREATE INDEX IF NOT EXISTS idx_chat_sessions_is_session_read
ON public.chat_sessions(is_session_read);

-- Step 4: Add documentation
COMMENT ON COLUMN public.chat_sessions.is_session_read IS 'Boolean flag indicating if human agent or admin has read this entire session';

COMMIT;

-- Verification queries:
-- Check that is_message_read is removed from chat_messages:
-- SELECT column_name FROM information_schema.columns WHERE table_name='chat_messages' AND column_name='is_message_read';
-- (Should return 0 rows)

-- Check that is_session_read exists in chat_sessions:
-- SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns 
-- WHERE table_name='chat_sessions' AND column_name='is_session_read';
-- (Should show: is_session_read, boolean, YES, false)
