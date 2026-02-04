-- Insert default roles into the roles table
-- This script creates the basic roles needed for the system

-- Insert admin role
INSERT INTO public.roles (role_name, role_description, created_at, updated_at) 
VALUES 
    ('admin', 'System administrator with full access to all features and settings', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_name) DO UPDATE SET
    role_description = EXCLUDED.role_description,
    updated_at = CURRENT_TIMESTAMP;

-- Insert human_agent role
INSERT INTO public.roles (role_name, role_description, created_at, updated_at) 
VALUES 
    ('human_agent', 'Human agent who can handle chat sessions and provide customer support', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_name) DO UPDATE SET
    role_description = EXCLUDED.role_description,
    updated_at = CURRENT_TIMESTAMP;

-- Insert user role (optional - for regular users)
INSERT INTO public.roles (role_name, role_description, created_at, updated_at) 
VALUES 
    ('user', 'Regular user with basic access to chat features', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_name) DO UPDATE SET
    role_description = EXCLUDED.role_description,
    updated_at = CURRENT_TIMESTAMP;

-- Verification query to check inserted roles
SELECT 
    id,
    role_name,
    role_description,
    created_at,
    updated_at
FROM public.roles 
WHERE role_name IN ('admin', 'human_agent', 'user')
ORDER BY role_name;
