-- Migration 007: Update session_assignments to use user_role_id instead of assignee_email and assignee_type
-- This migration simplifies the session_assignments table to use a proper foreign key relationship

-- Step 1: Create backup of existing data
CREATE TABLE IF NOT EXISTS session_assignments_backup AS 
SELECT * FROM session_assignments;

-- Step 2: Add the new user_role_id column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'session_assignments' AND column_name = 'user_role_id'
    ) THEN
        ALTER TABLE public.session_assignments ADD COLUMN user_role_id int4 NULL;
    END IF;
END $$;

-- Step 3: Migrate data from assignee_email to user_role_id
-- This maps existing email-based assignments to user_role_id
UPDATE session_assignments sa
SET user_role_id = urm.user_role_id
FROM user_role_mapping urm
JOIN users u ON urm.user_id = u.id
WHERE u.email = sa.assignee_email;

-- Step 4: Drop old columns and constraints
DO $$
BEGIN
    -- Drop old columns if they exist
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'session_assignments' AND column_name = 'assignee_email'
    ) THEN
        ALTER TABLE public.session_assignments DROP COLUMN assignee_email;
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'session_assignments' AND column_name = 'assignee_type'
    ) THEN
        ALTER TABLE public.session_assignments DROP COLUMN assignee_type;
    END IF;
    
    -- Drop old constraints if they exist
    ALTER TABLE public.session_assignments DROP CONSTRAINT IF EXISTS valid_assignee_type;
END $$;

-- Step 5: Make user_role_id NOT NULL and add foreign key constraint
ALTER TABLE public.session_assignments ALTER COLUMN user_role_id SET NOT NULL;

-- Add foreign key constraint
ALTER TABLE public.session_assignments 
ADD CONSTRAINT session_assignments_user_role_id_fkey 
FOREIGN KEY (user_role_id) REFERENCES public.user_role_mapping(user_role_id) ON DELETE CASCADE;

-- Step 6: Update indexes
-- Drop old indexes
DROP INDEX IF EXISTS idx_session_assignments_assignee;
DROP INDEX IF EXISTS idx_session_assignments_type;

-- Create new index for user_role_id
CREATE INDEX IF NOT EXISTS idx_session_assignments_user_role_id ON public.session_assignments USING btree (user_role_id);

-- Step 7: Update table comment
COMMENT ON TABLE public.session_assignments IS 'Tracks which user role is assigned to each session';

-- Step 8: Verify migration
SELECT 
    'session_assignments' as table_name,
    COUNT(*) as total_rows,
    COUNT(*) FILTER (WHERE user_role_id IS NOT NULL) as rows_with_user_role_id
FROM session_assignments;

-- Step 9: Optional: Clean up backup table after verification
-- Uncomment the line below after verifying the migration worked correctly
-- DROP TABLE IF EXISTS session_assignments_backup;
