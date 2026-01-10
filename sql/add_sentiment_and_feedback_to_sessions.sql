-- Migration: Add sentiment and session-level feedback to chat_sessions
-- This migration adds fields to track session-level sentiment and feedback

-- Add sentiment column to chat_sessions (can be NULL if not analyzed yet)
ALTER TABLE chat_sessions 
ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20) DEFAULT NULL; -- 'positive', 'negative', 'neutral'

-- Add session_feedback column to chat_sessions (aggregated from message-level feedback)
ALTER TABLE chat_sessions 
ADD COLUMN IF NOT EXISTS session_feedback VARCHAR(20) DEFAULT NULL; -- 'positive', 'negative', NULL

-- Add index for faster queries
CREATE INDEX IF NOT EXISTS idx_chat_sessions_sentiment ON chat_sessions(sentiment);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback ON chat_sessions(session_feedback);

-- Create a function to aggregate feedback from chat_feedback table to session level
-- This will be called when a session ends or when feedback is submitted
CREATE OR REPLACE FUNCTION update_session_feedback(session_uuid UUID)
RETURNS VOID AS $$
DECLARE
    session_id_str VARCHAR(255);
    positive_count INTEGER;
    negative_count INTEGER;
    final_feedback VARCHAR(20);
BEGIN
    -- Get the session_id string from the UUID
    SELECT cs.session_id INTO session_id_str
    FROM chat_sessions cs
    WHERE cs.id = session_uuid;
    
    IF session_id_str IS NULL THEN
        RETURN;
    END IF;
    
    -- Count positive and negative feedback for this session
    SELECT 
        COUNT(*) FILTER (WHERE feedback_type = 'positive'),
        COUNT(*) FILTER (WHERE feedback_type = 'negative')
    INTO positive_count, negative_count
    FROM chat_feedback
    WHERE session_id = session_id_str;
    
    -- Determine session-level feedback
    -- If there's any negative feedback, mark as negative
    -- Otherwise, if there's positive feedback, mark as positive
    -- If no feedback, leave as NULL
    IF negative_count > 0 THEN
        final_feedback := 'negative';
    ELSIF positive_count > 0 THEN
        final_feedback := 'positive';
    ELSE
        final_feedback := NULL;
    END IF;
    
    -- Update the session
    UPDATE chat_sessions
    SET session_feedback = final_feedback,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = session_uuid;
END;
$$ LANGUAGE plpgsql;

-- Create a trigger to automatically update session feedback when feedback is added
CREATE OR REPLACE FUNCTION trigger_update_session_feedback()
RETURNS TRIGGER AS $$
DECLARE
    session_uuid UUID;
BEGIN
    -- Find the session UUID from session_id string
    SELECT cs.id INTO session_uuid
    FROM chat_sessions cs
    WHERE cs.session_id = NEW.session_id
    LIMIT 1;
    
    IF session_uuid IS NOT NULL THEN
        PERFORM update_session_feedback(session_uuid);
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS trg_update_session_feedback ON chat_feedback;
CREATE TRIGGER trg_update_session_feedback
AFTER INSERT OR UPDATE ON chat_feedback
FOR EACH ROW
EXECUTE FUNCTION trigger_update_session_feedback();

COMMENT ON COLUMN chat_sessions.sentiment IS 'Overall sentiment of the chat session (positive, negative, neutral) - analyzed by LLM';
COMMENT ON COLUMN chat_sessions.session_feedback IS 'Aggregated feedback from customer (positive, negative) - from message-level feedback';
