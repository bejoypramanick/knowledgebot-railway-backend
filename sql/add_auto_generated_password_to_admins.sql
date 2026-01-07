-- Migration: Add auto_generated_password column to admins table
-- This column stores the auto-generated password that is sent to admins via email

-- Add auto_generated_password column to admins table
ALTER TABLE admins
ADD COLUMN IF NOT EXISTS auto_generated_password VARCHAR(255);

-- Add comment for documentation
COMMENT ON COLUMN admins.auto_generated_password IS 'Auto-generated password sent to admin via email. Admin can reset this or login with Google.';

