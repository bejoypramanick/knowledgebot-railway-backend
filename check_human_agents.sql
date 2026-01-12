-- Check human agents configuration
SELECT email, status, created_at FROM human_agents ORDER BY created_at DESC;

-- Check if there are any assigned sessions
SELECT
    cs.session_id,
    cs.archive_status,
    sa.assignee_email,
    sa.status as assignment_status,
    sa.assigned_at
FROM chat_sessions cs
LEFT JOIN session_assignments sa ON cs.id = sa.session_id
WHERE sa.assignee_email IS NOT NULL
ORDER BY sa.assigned_at DESC
LIMIT 10;

-- Check online status (agents who have accessed chat log recently)
SELECT DISTINCT
    sa.assignee_email,
    MAX(sa.assigned_at) as last_activity
FROM session_assignments sa
WHERE sa.assigned_at > NOW() - INTERVAL '30 minutes'
GROUP BY sa.assignee_email
ORDER BY last_activity DESC;