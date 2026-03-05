-- Script to check user roles and add admin role if needed
-- Replace 'your-email@example.com' with the actual admin email

-- Step 1: Check if user exists
SELECT 
    id,
    email,
    firebase_uid,
    created_at
FROM users 
WHERE email = 'your-email@example.com';

-- Step 2: Check current roles for the user
SELECT 
    u.email,
    r.role_name,
    urm.created_at as role_assigned_at
FROM users u
JOIN user_role_mapping urm ON u.id = urm.user_id
JOIN roles r ON urm.role_id = r.id
WHERE u.email = 'your-email@example.com';

-- Step 3: Check if admin role exists
SELECT id, role_name FROM roles WHERE role_name = 'admin';

-- Step 4: Check if human_agent role exists
SELECT id, role_name FROM roles WHERE role_name = 'human_agent';

-- Step 5: Add admin role to user (if not already assigned)
-- IMPORTANT: Replace 'your-email@example.com' with actual email
INSERT INTO user_role_mapping (user_id, role_id, created_at, updated_at)
SELECT 
    u.id,
    r.id,
    NOW(),
    NOW()
FROM users u
CROSS JOIN roles r
WHERE u.email = 'your-email@example.com'
  AND r.role_name = 'admin'
  AND NOT EXISTS (
    SELECT 1 
    FROM user_role_mapping urm2 
    WHERE urm2.user_id = u.id 
      AND urm2.role_id = r.id
  );

-- Step 6: Verify the role was added
SELECT 
    u.email,
    r.role_name,
    urm.created_at as role_assigned_at
FROM users u
JOIN user_role_mapping urm ON u.id = urm.user_id
JOIN roles r ON urm.role_id = r.id
WHERE u.email = 'your-email@example.com';

-- Alternative: Add human_agent role instead of admin
-- Uncomment if you want human_agent role instead
/*
INSERT INTO user_role_mapping (user_id, role_id, created_at, updated_at)
SELECT 
    u.id,
    r.id,
    NOW(),
    NOW()
FROM users u
CROSS JOIN roles r
WHERE u.email = 'your-email@example.com'
  AND r.role_name = 'human_agent'
  AND NOT EXISTS (
    SELECT 1 
    FROM user_role_mapping urm2 
    WHERE urm2.user_id = u.id 
      AND urm2.role_id = r.id
  );
*/

-- Step 7: If roles table is empty, create default roles first
-- Run this ONLY if Step 3 and 4 return no results
/*
INSERT INTO roles (role_name, description, created_at, updated_at)
VALUES 
    ('admin', 'Administrator with full access', NOW(), NOW()),
    ('human_agent', 'Human agent for chat support', NOW(), NOW()),
    ('user', 'Regular user', NOW(), NOW())
ON CONFLICT (role_name) DO NOTHING;
*/
