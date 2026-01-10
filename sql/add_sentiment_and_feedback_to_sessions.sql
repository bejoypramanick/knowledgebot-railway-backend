-- Migration: Add sentiment and session-level feedback to chat_sessions
-- This migration adds fields to track session-level sentiment and feedback
-- Note: Feedback aggregation is handled in application code, not via database triggers

-- Add sentiment column to chat_sessions (can be NULL if not analyzed yet)
ALTER TABLE chat_sessions 
ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20) DEFAULT NULL; -- 'positive', 'negative', 'neutral'

-- Add session_feedback column to chat_sessions (aggregated from message-level feedback)
ALTER TABLE chat_sessions 
ADD COLUMN IF NOT EXISTS session_feedback VARCHAR(20) DEFAULT NULL; -- 'positive', 'negative', NULL

-- Add index for faster queries
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment ON chat_sessions(sentiment);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback ON chat_sessions(session_feedback);

COMMENT ON COLUMN chat_sessions.sentiment IS 'Overall sentiment of the chat session (positive, negative, neutral) - analyzed by LLM';
COMMENT ON COLUMN chat_sessions.session_feedback IS 'Aggregated feedback from customer (positive, negative) - from message-level feedback. Updated by application code when feedback is submitted.';
