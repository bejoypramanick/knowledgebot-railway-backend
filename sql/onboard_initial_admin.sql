-- Onboard Initial Admin User
-- Replace 'admin@globistaan.com' with the actual email of the first admin user.

INSERT INTO admins (email, status, confirmed_at, created_by_email)
VALUES (
    '', -- CHANGE THIS EMAIL
    'confirmed',
    NOW(),
    'system_init'
)
ON CONFLICT (email) 
DO UPDATE SET 
    status = 'confirmed',
    confirmed_at = COALESCE(admins.confirmed_at, NOW()),
    removed_at = NULL;

