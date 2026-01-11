-- Database Migration: Admin Management and Roles System
-- Run this migration to add admin management and role-based access control

-- 1. Create Admins Table (replaces single admin_user field)
CREATE TABLE IF NOT EXISTS admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- 'pending', 'confirmed', 'removed'
    confirmation_token VARCHAR(255) UNIQUE,
    auto_generated_password VARCHAR(255), -- Auto-generated password sent to admin via email
    created_at TIMESTAMP DEFAULT NOW(),
    confirmed_at TIMESTAMP,
    removed_at TIMESTAMP,
    created_by_email VARCHAR(255), -- Email of admin who created this admin
    CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
);

CREATE INDEX IF NOT EXISTS idx_admins_email ON admins(email);
CREATE INDEX IF NOT EXISTS idx_admins_status ON admins(status);
CREATE INDEX IF NOT EXISTS idx_admins_token ON admins(confirmation_token);

-- 2. Update chatbot_configuration table to support multiple admins
-- Keep admin_user for backward compatibility, but it will now reference the first confirmed admin
ALTER TABLE chatbot_configuration 
ADD COLUMN IF NOT EXISTS admin_emails TEXT[] DEFAULT ARRAY[]::TEXT[];

-- 3. Migrate existing admin_user to admins table (if exists)
DO $$
DECLARE
    existing_admin VARCHAR(255);
BEGIN
    -- Check if admin_user exists and is not 'GLOBISTAAN'
    SELECT admin_user INTO existing_admin
    FROM chatbot_configuration
    WHERE admin_user IS NOT NULL AND admin_user != 'GLOBISTAAN'
    LIMIT 1;
    
    -- If we have an existing admin that looks like an email, migrate it
    IF existing_admin IS NOT NULL AND existing_admin ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$' THEN
        -- Insert into admins table if not exists
        INSERT INTO admins (email, status, confirmed_at)
        VALUES (existing_admin, 'confirmed', NOW())
        ON CONFLICT (email) DO NOTHING;
        
        -- Update chatbot_configuration to include this admin
        UPDATE chatbot_configuration
        SET admin_emails = ARRAY[existing_admin]
        WHERE admin_user = existing_admin;
    END IF;
END $$;

-- 4. Update human_agents table to include role
ALTER TABLE human_agents
ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'human_agent';

-- 5. Ensure all human agents have the correct role
UPDATE human_agents
SET role = 'human_agent'
WHERE role IS NULL OR role = '';

-- 6. Add role column to chatbot_configuration for default role assignment
ALTER TABLE chatbot_configuration
ADD COLUMN IF NOT EXISTS default_user_role VARCHAR(50) DEFAULT 'user';

-- 7. Create function to get user role from email
CREATE OR REPLACE FUNCTION get_user_role(user_email VARCHAR(255))
RETURNS VARCHAR(50) AS $$
DECLARE
    user_role VARCHAR(50);
BEGIN
    -- Check if user is an admin
    SELECT 'admin' INTO user_role
    FROM admins
    WHERE email = user_email AND status = 'confirmed'
    LIMIT 1;
    
    IF user_role IS NOT NULL THEN
        RETURN user_role;
    END IF;
    
    -- Check if user is a human agent
    SELECT 'human_agent' INTO user_role
    FROM human_agents
    WHERE email = user_email AND status = 'confirmed'
    LIMIT 1;
    
    IF user_role IS NOT NULL THEN
        RETURN user_role;
    END IF;
    
    -- Default to 'user'
    RETURN 'user';
END;
$$ LANGUAGE plpgsql;

-- 8. Create view for user roles (for easy querying)
CREATE OR REPLACE VIEW user_roles AS
SELECT 
    email,
    'admin' as role,
    status,
    confirmed_at as role_assigned_at
FROM admins
WHERE status IN ('confirmed', 'pending')
UNION ALL
SELECT 
    email,
    'human_agent' as role,
    status,
    confirmed_at as role_assigned_at
FROM human_agents
WHERE status IN ('confirmed', 'pending');

-- 9. Ensure auto_generated_password column exists (for existing installations)
ALTER TABLE admins
ADD COLUMN IF NOT EXISTS auto_generated_password VARCHAR(255);

-- 10. Add comments for documentation
COMMENT ON TABLE admins IS 'Stores admin users with email-based authentication and verification';
COMMENT ON COLUMN admins.auto_generated_password IS 'Auto-generated password sent to admin via email. Admin can reset this or login with Google.';
COMMENT ON TABLE human_agents IS 'Stores human agent users with email-based authentication';
COMMENT ON FUNCTION get_user_role IS 'Returns the role (admin, human_agent, or user) for a given email';
COMMENT ON VIEW user_roles IS 'Unified view of all user roles (admins and human agents)';

