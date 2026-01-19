-- Migration: Add user_profiles table
-- This migration adds the user_profiles table for storing extended user information

-- Create user_profiles table
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    uid VARCHAR(255) NOT NULL UNIQUE,  -- Firebase UID
    email VARCHAR(255),
    display_name VARCHAR(255),
    photo_url TEXT,
    role VARCHAR(50) DEFAULT 'user',
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMPTZ,
    CONSTRAINT user_profiles_role_check CHECK (role IN ('user', 'agent', 'admin')),
    CONSTRAINT user_profiles_email_check CHECK (email IS NULL OR email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_user_profiles_uid ON user_profiles(uid);
CREATE INDEX IF NOT EXISTS idx_user_profiles_email ON user_profiles(email);
CREATE INDEX IF NOT EXISTS idx_user_profiles_role ON user_profiles(role);

-- Add comment
COMMENT ON TABLE user_profiles IS 'Extended user profile information for authenticated users';

-- Optional: Pre-populate user_profiles with existing users (run this after the table creation above)
-- Uncomment and run these queries if you want to migrate existing users to the new table

/*
-- Migrate admins to user_profiles (assuming you have Firebase UIDs for them)
-- Note: You'll need to replace 'ADMIN_FIREBASE_UID_1', 'ADMIN_FIREBASE_UID_2', etc. with actual Firebase UIDs
INSERT INTO user_profiles (uid, email, role, display_name, created_at, updated_at)
SELECT
    CASE
        WHEN email = 'admin1@example.com' THEN 'ADMIN_FIREBASE_UID_1'
        WHEN email = 'admin2@example.com' THEN 'ADMIN_FIREBASE_UID_2'
        -- Add more mappings as needed
        ELSE CONCAT('MIGRATED_ADMIN_', REPLACE(email, '@', '_'))
    END as uid,
    email,
    'admin' as role,
    COALESCE(name, email) as display_name,
    COALESCE(confirmed_at, created_at) as created_at,
    CURRENT_TIMESTAMP as updated_at
FROM admins
WHERE status = 'confirmed' AND removed_at IS NULL
ON CONFLICT (uid) DO NOTHING;

-- Migrate human agents to user_profiles
INSERT INTO user_profiles (uid, email, role, display_name, created_at, updated_at)
SELECT
    CONCAT('MIGRATED_AGENT_', REPLACE(email, '@', '_')) as uid,
    email,
    'agent' as role,
    email as display_name,
    COALESCE(confirmed_at, created_at) as created_at,
    CURRENT_TIMESTAMP as updated_at
FROM human_agents
WHERE status = 'confirmed' AND removed_at IS NULL
ON CONFLICT (uid) DO NOTHING;

-- Migrate regular users to user_profiles (if any exist in the users table)
INSERT INTO user_profiles (uid, email, role, display_name, created_at, updated_at)
SELECT
    CONCAT('MIGRATED_USER_', REPLACE(email, '@', '_')) as uid,
    email,
    'user' as role,
    COALESCE(name, email) as display_name,
    created_at,
    CURRENT_TIMESTAMP as updated_at
FROM users
WHERE is_active = true
ON CONFLICT (uid) DO NOTHING;
*/

-- Migration complete
SELECT 'User profiles table migration completed successfully' as result;