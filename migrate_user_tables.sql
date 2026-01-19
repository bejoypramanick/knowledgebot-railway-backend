-- ============================================================================
-- DATABASE MIGRATION: User Profile Simplification
-- ============================================================================
-- This migration ensures required indexes exist on admins and human_agents tables.
-- No additional columns are needed since:
-- - display_name, photo_url come from Firebase authentication at runtime
-- - No user-specific preferences (all changes are global)
-- - created_at, updated_at already exist in tables

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_admins_email_status ON admins(email, status);
CREATE INDEX IF NOT EXISTS idx_human_agents_email_status ON human_agents(email, status);

-- ============================================================================
-- VERIFICATION QUERIES (Run after migration)
-- ============================================================================

-- Check that indexes were created:
-- SELECT indexname, tablename FROM pg_indexes
-- WHERE tablename IN ('admins', 'human_agents')
-- AND indexname LIKE '%email%status%';

-- Verify table structure (should NOT have profile columns):
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name IN ('admins', 'human_agents')
-- ORDER BY table_name, ordinal_position;

-- Test profile endpoint works:
-- SELECT email FROM admins WHERE status = 'confirmed' LIMIT 1;
-- SELECT email FROM human_agents WHERE status IN ('confirmed', 'pending') LIMIT 1;