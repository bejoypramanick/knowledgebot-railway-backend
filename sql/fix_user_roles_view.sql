-- STANDALONE FIX: Update user_roles view to include pending users
-- Run this in your Railway SQL Editor to apply the fix immediately

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

COMMENT ON VIEW user_roles IS 'Unified view of all user roles (admins and human agents), including pending status';
