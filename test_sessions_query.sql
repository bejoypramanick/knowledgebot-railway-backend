-- Test query to check if chat sessions exist in the database

-- Count total sessions
SELECT COUNT(*) as total_sessions FROM chat_sessions;

-- Show recent sessions
SELECT 
    id,
    session_id,
    archive_status,
    is_active,
    created_at,
    last_activity_at,
    metadata
FROM chat_sessions
ORDER BY created_at DESC
LIMIT 10;

-- Check session assignments
SELECT 
    sa.id,
    sa.session_id,
    sa.status,
    u.email as assigned_agent,
    sa.assigned_at
FROM session_assignments sa
LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
LEFT JOIN users u ON urm.user_id = u.id
ORDER BY sa.assigned_at DESC
LIMIT 10;

-- Check messages
SELECT 
    cm.id,
    cm.session_id,
    cm.role,
    LEFT(cm.content, 50) as content_preview,
    cm.created_at
FROM chat_messages cm
ORDER BY cm.created_at DESC
LIMIT 10;
