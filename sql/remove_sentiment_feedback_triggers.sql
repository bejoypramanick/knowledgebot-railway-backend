-- Cleanup Script: Remove triggers and functions for sentiment/feedback
-- Run this if you already ran the migration with triggers
-- This removes the database triggers and functions, as feedback aggregation
-- is now handled in application code instead

-- Drop the trigger first
DROP TRIGGER IF EXISTS trg_update_session_feedback ON chat_feedback;

-- Drop the trigger function
DROP FUNCTION IF EXISTS trigger_update_session_feedback();

-- Drop the update function (optional - can keep for manual use if needed)
-- Uncomment the line below if you want to remove it completely
-- DROP FUNCTION IF EXISTS update_session_feedback(UUID);

-- Note: The columns (sentiment, session_feedback) and indexes remain
-- Only the triggers and functions are removed

COMMENT ON COLUMN chat_sessions.sentiment IS 'Overall sentiment of the chat session (positive, negative, neutral) - analyzed by LLM. Updated by application code when session closes.';
COMMENT ON COLUMN chat_sessions.session_feedback IS 'Aggregated feedback from customer (positive, negative) - from message-level feedback. Updated by application code when feedback is submitted.';
