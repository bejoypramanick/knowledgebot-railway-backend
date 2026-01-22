-- Migration: Remove unused columns after removing email confirmation system
-- This removes columns that are no longer needed since admins and agents are activated immediately

-- Remove unused columns from admins table
ALTER TABLE admins DROP COLUMN IF EXISTS status;
ALTER TABLE admins DROP COLUMN IF EXISTS confirmation_token;
ALTER TABLE admins DROP COLUMN IF EXISTS auto_generated_password;
ALTER TABLE admins DROP COLUMN IF EXISTS confirmed_at;

-- Remove unused columns from human_agents table
ALTER TABLE human_agents DROP COLUMN IF EXISTS status;
ALTER TABLE human_agents DROP COLUMN IF EXISTS confirmation_token;
ALTER TABLE human_agents DROP COLUMN IF EXISTS auto_generated_password;
ALTER TABLE human_agents DROP COLUMN IF EXISTS confirmed_at;

-- Drop the status-related indexes that are no longer needed
DROP INDEX IF EXISTS idx_admins_status;
DROP INDEX IF EXISTS idx_human_agents_status;
DROP INDEX IF EXISTS idx_admins_token;
DROP INDEX IF EXISTS idx_human_agents_token;

-- Update comments to reflect the simplified structure
COMMENT ON TABLE admins IS 'Admin users with immediate activation (no confirmation needed)';
COMMENT ON TABLE human_agents IS 'Human agents with immediate activation (no confirmation needed)';

-- Verify the changes
SELECT
    'Admins table columns:' as info,
    array_agg(column_name::text) as columns
FROM information_schema.columns
WHERE table_name = 'admins' AND table_schema = 'public';

SELECT
    'Human agents table columns:' as info,
    array_agg(column_name::text) as columns
FROM information_schema.columns
WHERE table_name = 'human_agents' AND table_schema = 'public';