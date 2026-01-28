-- Migration 001: Add missing status column to admins table
-- The admins table exists but is missing the status column needed for role management

-- Add status column to admins table (check if column exists first)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='admins' AND column_name='status' AND table_schema='public'
    ) THEN
        ALTER TABLE public.admins ADD COLUMN status varchar(50) DEFAULT 'active' NOT NULL;
    END IF;
END $$;

-- Add constraint for status column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.check_constraints 
        WHERE constraint_name = 'admins_status_check'
    ) THEN
        ALTER TABLE public.admins 
        ADD CONSTRAINT admins_status_check 
        CHECK (status IN ('active', 'inactive', 'removed'));
    END IF;
END $$;

-- Create index for status column
CREATE INDEX IF NOT EXISTS idx_admins_status ON public.admins USING btree (status);

-- Update existing records to have active status (in case column was added without default)
UPDATE public.admins SET status = 'active' WHERE status IS NULL;

-- Add comments
COMMENT ON COLUMN public.admins.status IS 'Admin status: active (can access), inactive (suspended), removed (deleted)';

-- Verify the column was added
SELECT 
    column_name, 
    data_type, 
    is_nullable, 
    column_default
FROM information_schema.columns 
WHERE table_schema = 'public' 
    AND table_name = 'admins' 
    AND column_name = 'status';
