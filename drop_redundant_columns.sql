-- ============================================================================
-- DROP REDUNDANT COLUMNS: Remove unused profile columns
-- ============================================================================
-- These columns were added in previous migrations but are not needed:
-- - display_name, photo_url: Come from Firebase at runtime
-- - last_login, preferences: Not needed (no user preferences)
-- - created_at, updated_at: Already exist in tables

-- Drop redundant columns from admins table
ALTER TABLE admins
DROP COLUMN IF EXISTS display_name,
DROP COLUMN IF EXISTS photo_url,
DROP COLUMN IF EXISTS last_login,
DROP COLUMN IF EXISTS preferences;

-- Drop redundant columns from human_agents table
ALTER TABLE human_agents
DROP COLUMN IF EXISTS display_name,
DROP COLUMN IF EXISTS photo_url,
DROP COLUMN IF EXISTS last_login,
DROP COLUMN IF EXISTS preferences;

-- ============================================================================
-- VERIFICATION QUERIES (Run after dropping columns)
-- ============================================================================

-- Verify columns were dropped:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name IN ('admins', 'human_agents')
-- AND column_name IN ('display_name', 'photo_url', 'last_login', 'preferences')
-- ORDER BY table_name, column_name;

-- Should return no rows if columns were successfully dropped

-- Verify core columns still exist:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name IN ('admins', 'human_agents')
-- AND column_name NOT IN ('display_name', 'photo_url', 'last_login', 'preferences')
-- ORDER BY table_name, ordinal_position;</content>
</xai:function_call: Wrote contents to /Users/bejoypramanick/iCloud Drive (Archive) - 1/Desktop/globistaan/projects/knowledgebot-railway-backend/drop_redundant_columns.sql