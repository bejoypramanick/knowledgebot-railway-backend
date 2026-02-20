-- Performance Optimization Indexes
-- Created: 2026-02-08
-- Purpose: Add indexes to improve query performance for chat sessions and feedback

-- Index for feedback counts query (used in batch feedback lookup)
CREATE INDEX IF NOT EXISTS idx_chat_feedback_session_id 
ON chat_feedback(session_id);

-- Index for session assignments lookup
CREATE INDEX IF NOT EXISTS idx_session_assignments_session_id 
ON session_assignments(session_id);

-- Index for user email lookups in user_role_mapping joins
CREATE INDEX IF NOT EXISTS idx_users_email 
ON users(email);

-- Index for chat sessions ordered by last activity (used in pagination)
CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_activity 
ON chat_sessions(last_activity_at DESC);

-- Index for archive status filtering
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_status 
ON chat_sessions(archive_status);

-- Composite index for common query pattern (archive status + last activity)
CREATE INDEX IF NOT EXISTS idx_chat_sessions_archive_activity 
ON chat_sessions(archive_status, last_activity_at DESC);

-- Index for user_role_mapping lookups
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_user_id 
ON user_role_mapping(user_id);

CREATE INDEX IF NOT EXISTS idx_user_role_mapping_role_id 
ON user_role_mapping(role_id);

-- Index for session_assignments by user_role_id (for agent chat counts)
CREATE INDEX IF NOT EXISTS idx_session_assignments_user_role_id_status 
ON session_assignments(user_role_id, status);

-- Index for chat messages by session (for message retrieval)
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id 
ON chat_messages(session_id, created_at ASC);

-- Analyze tables to update statistics
ANALYZE chat_feedback;
ANALYZE session_assignments;
ANALYZE users;
ANALYZE chat_sessions;
ANALYZE user_role_mapping;
ANALYZE chat_messages;
