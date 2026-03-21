-- Add is_session_read column to chat_sessions for mark-read/unread feature
ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS is_session_read boolean DEFAULT false;
