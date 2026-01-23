-- Migration: Fix chat_sessions archive_status column
-- Ensure all existing chat_sessions have proper archive_status values

-- Add archive_status column if it doesn't exist (should already exist from previous migration)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'chat_sessions'
                   AND column_name = 'archive_status') THEN
        ALTER TABLE chat_sessions ADD COLUMN archive_status VARCHAR(50) DEFAULT 'active';
        CREATE INDEX idx_chat_sessions_archive_status ON chat_sessions(archive_status);
        CREATE INDEX idx_chat_sessions_archive_status_updated ON chat_sessions(archive_status, updated_at DESC);
    END IF;
END $$;

-- Update existing sessions that don't have archive_status set
-- Active sessions (is_active = true) should be 'active'
-- Inactive sessions (is_active = false) should be 'closed'
UPDATE chat_sessions
SET archive_status = CASE
    WHEN is_active = true THEN 'active'
    WHEN is_active = false THEN 'closed'
    ELSE 'active'
END
WHERE archive_status IS NULL OR archive_status = '';

-- Ensure all sessions have a valid archive_status
UPDATE chat_sessions
SET archive_status = 'active'
WHERE archive_status NOT IN ('active', 'closed', 'archived', 'transferred');

-- Log the changes
SELECT
    'Migration completed' as status,
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN archive_status = 'active' THEN 1 END) as active_sessions,
    COUNT(CASE WHEN archive_status = 'closed' THEN 1 END) as closed_sessions,
    COUNT(CASE WHEN archive_status = 'archived' THEN 1 END) as archived_sessions,
    COUNT(CASE WHEN archive_status = 'transferred' THEN 1 END) as transferred_sessions
FROM chat_sessions;

COMMENT ON COLUMN chat_sessions.archive_status IS 'Session status: active (ongoing), closed (finished), archived (manually archived), transferred (moved to another agent)';