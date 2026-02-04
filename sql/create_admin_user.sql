-- Create admin user globistaan@gmail.com with admin and human_agent roles
-- This script creates the main administrator user for the system

-- First, ensure the roles exist (run insert_roles.sql first if needed)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.roles WHERE role_name = 'admin') THEN
        RAISE EXCEPTION 'Admin role not found. Please run insert_roles.sql first';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM public.roles WHERE role_name = 'human_agent') THEN
        RAISE EXCEPTION 'Human agent role not found. Please run insert_roles.sql first';
    END IF;
END $$;

-- Create the user
INSERT INTO public.users (email, is_active, created_at, updated_at) 
VALUES 
    ('globistaan@gmail.com', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (email) DO UPDATE SET
    is_active = EXCLUDED.is_active,
    updated_at = CURRENT_TIMESTAMP
RETURNING id, email, is_active, created_at, updated_at;

-- Get the user ID and role IDs for role assignments
DO $$
DECLARE
    user_id_val INTEGER;
    admin_role_id INTEGER;
    human_agent_role_id INTEGER;
BEGIN
    -- Get the user ID
    SELECT id INTO user_id_val FROM public.users WHERE email = 'globistaan@gmail.com';
    
    -- Get role IDs
    SELECT id INTO admin_role_id FROM public.roles WHERE role_name = 'admin';
    SELECT id INTO human_agent_role_id FROM public.roles WHERE role_name = 'human_agent';
    
    -- Assign admin role
    INSERT INTO public.user_role_mapping (user_id, role_id, is_active, created_at, updated_at)
    VALUES (user_id_val, admin_role_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (user_id, role_id) DO UPDATE SET
        is_active = EXCLUDED.is_active,
        updated_at = CURRENT_TIMESTAMP;
    
    -- Assign human_agent role
    INSERT INTO public.user_role_mapping (user_id, role_id, is_active, created_at, updated_at)
    VALUES (user_id_val, human_agent_role_id, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (user_id, role_id) DO UPDATE SET
        is_active = EXCLUDED.is_active,
        updated_at = CURRENT_TIMESTAMP;
    
    RAISE NOTICE 'User globistaan@gmail.com created and assigned admin and human_agent roles';
END $$;

-- Verification query to show the created user and their roles
SELECT 
    u.id as user_id,
    u.email,
    u.is_active as user_active,
    u.created_at as user_created_at,
    u.updated_at as user_updated_at,
    r.role_name,
    r.role_description,
    urm.is_active as role_mapping_active,
    urm.created_at as role_assigned_at
FROM public.users u
JOIN public.user_role_mapping urm ON u.id = urm.user_id
JOIN public.roles r ON urm.role_id = r.id
WHERE u.email = 'globistaan@gmail.com'
ORDER BY r.role_name;
