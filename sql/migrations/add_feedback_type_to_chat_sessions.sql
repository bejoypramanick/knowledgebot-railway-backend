-- Migration: Add feedback_type column to chat_sessions table
-- Date: 2026-03-02
-- Description: Add feedback_type column to track customer feedback (positive/negative) on chat sessions

BEGIN;

-- Add feedback_type column if it doesn't exist
ALTER TABLE chat_sessions
ADD COLUMN IF NOT EXISTS feedback_type varchar(20);

-- Add check constraint for valid feedback types
ALTER TABLE chat_sessions
ADD CONSTRAINT IF NOT EXISTS chat_sessions_feedback_type_check
CHECK (feedback_type IS NULL OR feedback_type IN ('positive', 'negative'));

-- Add feedback_provided_at column to track when feedback was given
ALTER TABLE chat_sessions
ADD COLUMN IF NOT EXISTS feedback_provided_at timestamp;

-- Create index for feedback queries
CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback_type
ON chat_sessions(feedback_type)
WHERE feedback_type IS NOT NULL;

-- Create index for feedback timestamp
CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback_provided_at
ON chat_sessions(feedback_provided_at)
WHERE feedback_provided_at IS NOT NULL;

-- Add comment
COMMENT ON COLUMN chat_sessions.feedback_type IS 'Customer feedback on chat session: positive (thumbs up) or negative (thumbs down). NULL if no feedback provided.';
COMMENT ON COLUMN chat_sessions.feedback_provided_at IS 'Timestamp when customer provided feedback on this session.';

COMMIT;
