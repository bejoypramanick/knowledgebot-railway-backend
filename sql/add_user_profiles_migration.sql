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

-- Migration complete
SELECT 'User profiles table migration completed successfully' as result;