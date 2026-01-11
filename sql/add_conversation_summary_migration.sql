-- Migration to add conversation_summary field to chat_sessions table
-- This enables storing AI-generated conversation summaries when sessions end

-- Add conversation_summary column
ALTER TABLE chat_sessions
ADD COLUMN conversation_summary TEXT;

-- Add index for better query performance (optional, for future filtering by summary content)
CREATE INDEX idx_chat_sessions_conversation_summary ON chat_sessions USING gin(to_tsvector('english', conversation_summary));

-- Add comment
COMMENT ON COLUMN chat_sessions.conversation_summary IS 'AI-generated summary of the conversation, created when session ends';

-- Migration complete