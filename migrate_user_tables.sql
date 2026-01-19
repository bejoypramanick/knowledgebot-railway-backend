-- Migration: Add user profile fields to admins and human_agents tables
-- This eliminates the need for the separate user_profiles table

-- Add profile columns to admins table
ALTER TABLE admins
ADD COLUMN IF NOT EXISTS display_name TEXT,
ADD COLUMN IF NOT EXISTS photo_url TEXT,
ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Add profile columns to human_agents table
ALTER TABLE human_agents
ADD COLUMN IF NOT EXISTS display_name TEXT,
ADD COLUMN IF NOT EXISTS photo_url TEXT,
ADD COLUMN IF NOT EXISTS last_login TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS preferences JSONB DEFAULT '{}',
ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_admins_email_status ON admins(email, status);
CREATE INDEX IF NOT EXISTS idx_human_agents_email_status ON human_agents(email, status);

-- Optional: Migrate existing data from user_profiles (run this only once)
-- INSERT INTO admins (email, display_name, photo_url, last_login, preferences, created_at)
-- SELECT email, display_name, photo_url, last_login, preferences, created_at
-- FROM user_profiles
-- WHERE role = 'admin' AND email IN (SELECT email FROM admins WHERE status = 'confirmed')
-- ON CONFLICT (email) DO NOTHING;

-- INSERT INTO human_agents (email, display_name, photo_url, last_login, preferences, created_at)
-- SELECT email, display_name, photo_url, last_login, preferences, created_at
-- FROM user_profiles
-- WHERE role = 'human_agent' AND email IN (SELECT email FROM human_agents WHERE status IN ('confirmed', 'pending'))
-- ON CONFLICT (email) DO NOTHING;

-- After verifying the migration works, you can drop the user_profiles table:
-- DROP TABLE IF EXISTS user_profiles;