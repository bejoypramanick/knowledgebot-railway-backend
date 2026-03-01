-- Migration: 008_migrate_feedback_to_chat_sessions.sql
-- Date: 2026-03-01
-- Author: Claude
-- Description: Migrate feedback from separate chat_feedback table to chat_sessions table

-- ============================================================================
-- OVERVIEW OF CHANGES
-- ============================================================================
-- This migration consolidates feedback into the chat_sessions table since
-- there is a 1-to-1 relationship between sessions and feedback (one feedback per session).
-- Feedback only comes from external/customer users, not admins or human agents.
--
-- Changes:
-- 1. Add feedback columns to chat_sessions table (only feedback_type and timestamp)
-- 2. Migrate existing feedback data from chat_feedback to chat_sessions
-- 3. Drop the chat_feedback table (no longer needed)
-- 4. Create indexes for feedback queries

BEGIN TRANSACTION;

-- Step 1: Add feedback columns to chat_sessions (external user feedback only)
ALTER TABLE public.chat_sessions
ADD COLUMN IF NOT EXISTS feedback_type varchar(20),
ADD COLUMN IF NOT EXISTS feedback_provided_at timestamp;

-- Step 2: Add constraint to feedback_type
ALTER TABLE public.chat_sessions
ADD CONSTRAINT chat_sessions_feedback_type_check
CHECK (feedback_type IS NULL OR feedback_type IN ('positive', 'negative'));

-- Step 3: Migrate data from chat_feedback to chat_sessions (if chat_feedback exists)
-- This will update chat_sessions with feedback data for matching session_ids
UPDATE public.chat_sessions cs
SET
    feedback_type = cf.feedback_type,
    feedback_provided_at = cf.created_at
FROM public.chat_feedback cf
WHERE cs.session_id = cf.session_id;

-- Step 4: Create indexes for feedback queries
CREATE INDEX IF NOT EXISTS idx_chat_sessions_feedback_type
ON public.chat_sessions(feedback_type);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_has_feedback
ON public.chat_sessions(session_id)
WHERE feedback_type IS NOT NULL;

-- Step 5: Drop the chat_feedback table (no longer needed)
DROP TABLE IF EXISTS public.chat_feedback CASCADE;

-- Step 6: Add column documentation
COMMENT ON COLUMN public.chat_sessions.feedback_type IS 'Customer feedback on chat session: positive (thumbs up) or negative (thumbs down). NULL if no feedback provided. Feedback from external users only.';
COMMENT ON COLUMN public.chat_sessions.feedback_provided_at IS 'Timestamp when customer feedback was provided.';

-- ============================================================================
-- ROLLBACK INSTRUCTIONS (if needed)
-- ============================================================================
-- If this migration needs to be rolled back, recreate the chat_feedback table:
--
-- CREATE TABLE public.chat_feedback (
--     id serial4 NOT NULL,
--     message_id varchar(255) NOT NULL,
--     session_id varchar(255) NOT NULL,
--     feedback_type varchar(20) NOT NULL,
--     user_role_id int4 NULL,
--     created_at timestamp DEFAULT now() NULL,
--     updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
--     CONSTRAINT chat_feedback_pkey PRIMARY KEY (id),
--     CONSTRAINT valid_feedback_type CHECK (feedback_type IN ('positive', 'negative')),
--     CONSTRAINT chat_feedback_user_role_id_fkey FOREIGN KEY (user_role_id)
--         REFERENCES public.user_role_mapping(user_role_id) ON DELETE SET NULL
-- );
--
-- Then remove feedback columns from chat_sessions:
-- ALTER TABLE public.chat_sessions
-- DROP CONSTRAINT IF EXISTS chat_sessions_feedback_type_check,
-- DROP COLUMN IF EXISTS feedback_type,
-- DROP COLUMN IF EXISTS feedback_provided_at;

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- After running this migration, verify the changes with:
--
-- 1. Check that feedback columns exist in chat_sessions:
--    SELECT column_name FROM information_schema.columns
--    WHERE table_name='chat_sessions' AND column_name LIKE 'feedback%';
--    (Should return: feedback_type, feedback_provided_at)
--
-- 2. Check that chat_feedback table is dropped:
--    SELECT EXISTS(SELECT 1 FROM information_schema.tables
--    WHERE table_name='chat_feedback');
--    (Should return: false)
--
-- 3. Check data migration:
--    SELECT COUNT(*) as sessions_with_feedback FROM public.chat_sessions
--    WHERE feedback_type IS NOT NULL;

