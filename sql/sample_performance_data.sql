-- Sample data for testing Chat Agent Performance charts
-- This script creates sample chat sessions and messages to populate performance metrics

-- Insert sample chat sessions from the last 30 days
INSERT INTO chat_sessions (id, session_id, user_id, customer_name, customer_email, status, sentiment, created_at, last_activity_at, is_active)
SELECT
    gen_random_uuid(),
    gen_random_uuid(),
    NULL, -- No user association for anonymous chats
    CASE (random() * 10)::int
        WHEN 0 THEN 'John Doe'
        WHEN 1 THEN 'Jane Smith'
        WHEN 2 THEN 'Bob Johnson'
        WHEN 3 THEN 'Alice Brown'
        WHEN 4 THEN 'Charlie Wilson'
        WHEN 5 THEN 'Diana Davis'
        WHEN 6 THEN 'Edward Miller'
        WHEN 7 THEN 'Fiona Garcia'
        WHEN 8 THEN 'George Martinez'
        WHEN 9 THEN 'Helen Lopez'
        ELSE 'Anonymous User'
    END,
    CASE (random() * 10)::int
        WHEN 0 THEN 'john@example.com'
        WHEN 1 THEN 'jane@example.com'
        WHEN 2 THEN 'bob@example.com'
        WHEN 3 THEN 'alice@example.com'
        WHEN 4 THEN 'charlie@example.com'
        WHEN 5 THEN 'diana@example.com'
        WHEN 6 THEN 'edward@example.com'
        WHEN 7 THEN 'fiona@example.com'
        WHEN 8 THEN 'george@example.com'
        WHEN 9 THEN 'helen@example.com'
        ELSE 'anonymous@example.com'
    END,
    CASE (random() * 3)::int
        WHEN 0 THEN 'active'
        WHEN 1 THEN 'closed'
        WHEN 2 THEN 'archived'
        ELSE 'completed'
    END,
    CASE (random() * 3)::int
        WHEN 0 THEN 'positive'
        WHEN 1 THEN 'neutral'
        WHEN 2 THEN 'negative'
        ELSE NULL
    END,
    CURRENT_TIMESTAMP - (random() * interval '30 days'),
    CURRENT_TIMESTAMP - (random() * interval '7 days'),
    CASE WHEN random() > 0.7 THEN false ELSE true END
FROM generate_series(1, 100); -- Create 100 sample sessions

-- Insert sample chat messages for the sessions
INSERT INTO chat_messages (id, session_id, role, content, created_at)
SELECT
    gen_random_uuid(),
    cs.id,
    CASE (random() * 2)::int
        WHEN 0 THEN 'user'
        WHEN 1 THEN 'assistant'
        ELSE 'system'
    END,
    CASE
        WHEN random() < 0.3 THEN 'Hello, I need help with my order'
        WHEN random() < 0.6 THEN 'Thank you for your assistance'
        WHEN random() < 0.8 THEN 'Can you help me with a refund?'
        ELSE 'I have a question about shipping'
    END,
    cs.created_at + (random() * (cs.last_activity_at - cs.created_at))
FROM chat_sessions cs
CROSS JOIN generate_series(1, (random() * 10 + 2)::int) AS msg_num; -- 2-12 messages per session

-- Insert sample feedback data
INSERT INTO feedback (id, session_id, feedback_type, rating, comment, created_at)
SELECT
    gen_random_uuid(),
    cs.id,
    'satisfaction',
    CASE (random() * 2)::int
        WHEN 0 THEN 'positive'
        WHEN 1 THEN 'negative'
        ELSE 'neutral'
    END,
    CASE WHEN random() > 0.7 THEN 'Great service!' ELSE NULL END,
    cs.last_activity_at
FROM chat_sessions cs
WHERE random() > 0.5; -- 50% of sessions have feedback

-- Insert sample token usage data for the last 30 days
INSERT INTO token_usage (id, provider, tokens_used, tokens_available, cost, created_at)
SELECT
    gen_random_uuid(),
    'gemini',
    (random() * 10000 + 1000)::int,
    20000,
    (random() * 0.1)::decimal(10,4),
    CURRENT_TIMESTAMP - (random() * interval '30 days')
FROM generate_series(1, 30); -- 30 days of data

COMMIT;

-- Display summary of inserted data
SELECT
    'Chat Sessions' as table_name,
    COUNT(*) as record_count
FROM chat_sessions
WHERE created_at >= CURRENT_TIMESTAMP - interval '30 days'

UNION ALL

SELECT
    'Chat Messages' as table_name,
    COUNT(*) as record_count
FROM chat_messages cm
JOIN chat_sessions cs ON cm.session_id = cs.id
WHERE cs.created_at >= CURRENT_TIMESTAMP - interval '30 days'

UNION ALL

SELECT
    'Feedback' as table_name,
    COUNT(*) as record_count
FROM feedback f
JOIN chat_sessions cs ON f.session_id = cs.id
WHERE cs.created_at >= CURRENT_TIMESTAMP - interval '30 days'

UNION ALL

SELECT
    'Token Usage' as table_name,
    COUNT(*) as record_count
FROM token_usage
WHERE created_at >= CURRENT_TIMESTAMP - interval '30 days';