-- Migration to add archive_status column to chat_sessions table
-- This enables proper status management for active, closed, archived, and transferred conversations

-- Add archive_status column with default value 'active'
ALTER TABLE chat_sessions
ADD COLUMN archive_status VARCHAR(20) DEFAULT 'active'
CHECK (archive_status IN ('active', 'closed', 'archived', 'transferred'));

-- Create index for better query performance
CREATE INDEX idx_chat_sessions_archive_status ON chat_sessions(archive_status);
CREATE INDEX idx_chat_sessions_archive_status_updated ON chat_sessions(archive_status, updated_at DESC);

-- Update existing sessions based on current logic
-- Sessions that are currently active should stay 'active'
-- Sessions that are closed should be 'closed'
UPDATE chat_sessions
SET archive_status = 'closed'
WHERE is_active = FALSE;

-- Add comment
COMMENT ON COLUMN chat_sessions.archive_status IS 'Session status: active (ongoing), closed (finished), archived (manually archived), transferred (moved to another agent)';

-- Migration complete