-- ============================================================================
-- TOKEN USAGE DEBUGGING QUERIES
-- Use these SELECT queries to debug token usage tracking issues
-- ============================================================================

-- 1. Check if token_usage_log table exists and has the correct structure
SELECT
    table_name,
    table_type
FROM information_schema.tables
WHERE table_name = 'token_usage_log';

-- 2. Check token_usage_log table structure (columns)
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'token_usage_log'
ORDER BY ordinal_position;

-- 3. Check if the detailed token fields exist (cache_read_tokens, etc.)
SELECT
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'token_usage_log'
AND column_name IN ('cache_read_tokens', 'cache_write_tokens', 'input_audio_tokens', 'cache_audio_read_tokens')
ORDER BY column_name;

-- 4. Check token_usage_cache table
SELECT
    provider,
    used,
    available,
    limit_value,
    last_updated
FROM token_usage_cache;

-- 5. Get total count of token usage log entries
SELECT COUNT(*) as total_token_log_entries FROM token_usage_log;

-- 6. Get recent token usage log entries (last 10)
SELECT
    id,
    session_id,
    message_id,
    provider,
    model,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    cache_read_tokens,
    cache_write_tokens,
    input_audio_tokens,
    cache_audio_read_tokens,
    api_call_type,
    created_at
FROM token_usage_log
ORDER BY created_at DESC
LIMIT 10;

-- 7. Get token usage by provider
SELECT
    provider,
    COUNT(*) as total_calls,
    SUM(prompt_tokens) as total_prompt_tokens,
    SUM(completion_tokens) as total_completion_tokens,
    SUM(total_tokens) as total_tokens_used,
    MIN(created_at) as first_usage,
    MAX(created_at) as last_usage
FROM token_usage_log
GROUP BY provider
ORDER BY total_tokens_used DESC;

-- 8. Get token usage by API call type
SELECT
    api_call_type,
    COUNT(*) as total_calls,
    SUM(prompt_tokens) as total_prompt_tokens,
    SUM(completion_tokens) as total_completion_tokens,
    SUM(total_tokens) as total_tokens_used
FROM token_usage_log
GROUP BY api_call_type
ORDER BY total_calls DESC;

-- 9. Get token usage by model
SELECT
    model,
    COUNT(*) as total_calls,
    SUM(prompt_tokens) as total_prompt_tokens,
    SUM(completion_tokens) as total_completion_tokens,
    SUM(total_tokens) as total_tokens_used
FROM token_usage_log
GROUP BY model
ORDER BY total_tokens_used DESC;

-- 10. Get recent sessions with token usage
SELECT DISTINCT
    tul.session_id,
    COUNT(tul.id) as token_log_entries,
    SUM(tul.total_tokens) as total_tokens_used,
    MAX(tul.created_at) as last_activity
FROM token_usage_log tul
JOIN chat_sessions cs ON tul.session_id = cs.id::text
GROUP BY tul.session_id
ORDER BY last_activity DESC
LIMIT 5;

-- 11. Check for any NULL values in critical fields
SELECT
    COUNT(*) as total_rows,
    COUNT(CASE WHEN session_id IS NULL THEN 1 END) as null_session_ids,
    COUNT(CASE WHEN message_id IS NULL THEN 1 END) as null_message_ids,
    COUNT(CASE WHEN provider IS NULL THEN 1 END) as null_providers,
    COUNT(CASE WHEN total_tokens IS NULL OR total_tokens = 0 THEN 1 END) as zero_or_null_total_tokens
FROM token_usage_log;

-- 12. Get token usage summary by hour (last 24 hours)
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    provider,
    COUNT(*) as calls,
    SUM(total_tokens) as total_tokens_used
FROM token_usage_log
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', created_at), provider
ORDER BY hour DESC, total_tokens_used DESC;

-- 13. Check for duplicate entries (same session + message + provider)
SELECT
    session_id,
    message_id,
    provider,
    COUNT(*) as duplicate_count
FROM token_usage_log
GROUP BY session_id, message_id, provider
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 10;

-- 14. Check token usage log entries with cache tokens (should be > 0 for OpenAI)
SELECT
    id,
    provider,
    model,
    cache_read_tokens,
    cache_write_tokens,
    total_tokens,
    created_at
FROM token_usage_log
WHERE (cache_read_tokens > 0 OR cache_write_tokens > 0)
ORDER BY created_at DESC
LIMIT 10;

-- 15. Check for entries with audio tokens
SELECT
    id,
    provider,
    model,
    input_audio_tokens,
    cache_audio_read_tokens,
    total_tokens,
    created_at
FROM token_usage_log
WHERE (input_audio_tokens > 0 OR cache_audio_read_tokens > 0)
ORDER BY created_at DESC
LIMIT 10;

-- 16. Check if chat_sessions table has corresponding entries
SELECT
    tul.session_id,
    cs.id as chat_session_exists,
    COUNT(tul.id) as token_entries,
    SUM(tul.total_tokens) as total_tokens
FROM token_usage_log tul
LEFT JOIN chat_sessions cs ON tul.session_id = cs.id::text
GROUP BY tul.session_id, cs.id
ORDER BY token_entries DESC
LIMIT 10;

-- 17. Check if chat_messages table has corresponding entries
SELECT
    tul.message_id,
    cm.id as chat_message_exists,
    tul.provider,
    tul.total_tokens,
    tul.created_at
FROM token_usage_log tul
LEFT JOIN chat_messages cm ON tul.message_id = cm.id::text
WHERE cm.id IS NULL
ORDER BY tul.created_at DESC
LIMIT 10;

-- 18. Get the most recent token usage entries with full details
SELECT
    tul.*,
    cs.user_id,
    cm.role,
    cm.content_length
FROM token_usage_log tul
LEFT JOIN chat_sessions cs ON tul.session_id = cs.id::text
LEFT JOIN chat_messages cm ON tul.message_id = cm.id::text
ORDER BY tul.created_at DESC
LIMIT 5;

-- 19. Check for any orphaned token usage entries (no corresponding session/message)
SELECT
    COUNT(*) as total_entries,
    COUNT(CASE WHEN cs.id IS NULL THEN 1 END) as orphaned_sessions,
    COUNT(CASE WHEN cm.id IS NULL THEN 1 END) as orphaned_messages
FROM token_usage_log tul
LEFT JOIN chat_sessions cs ON tul.session_id = cs.id::text
LEFT JOIN chat_messages cm ON tul.message_id = cm.id::text;

-- 20. Check database constraints and indexes on token_usage_log
SELECT
    conname as constraint_name,
    contype as constraint_type,
    conrelid::regclass as table_name
FROM pg_constraint
WHERE conrelid = 'token_usage_log'::regclass;

SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'token_usage_log';

-- ============================================================================
-- QUICK DIAGNOSTIC QUERIES
-- ============================================================================

-- Quick check: Are there any token usage records at all?
SELECT
    CASE
        WHEN COUNT(*) > 0 THEN '✅ Token usage records exist'
        ELSE '❌ No token usage records found'
    END as status,
    COUNT(*) as total_records
FROM token_usage_log;

-- Quick check: Are detailed fields populated?
SELECT
    'cache_read_tokens' as field,
    COUNT(*) as total_records,
    COUNT(CASE WHEN cache_read_tokens > 0 THEN 1 END) as non_zero_values
FROM token_usage_log
UNION ALL
SELECT
    'cache_write_tokens' as field,
    COUNT(*) as total_records,
    COUNT(CASE WHEN cache_write_tokens > 0 THEN 1 END) as non_zero_values
FROM token_usage_log
UNION ALL
SELECT
    'input_audio_tokens' as field,
    COUNT(*) as total_records,
    COUNT(CASE WHEN input_audio_tokens > 0 THEN 1 END) as non_zero_values
FROM token_usage_log
UNION ALL
SELECT
    'cache_audio_read_tokens' as field,
    COUNT(*) as total_records,
    COUNT(CASE WHEN cache_audio_read_tokens > 0 THEN 1 END) as non_zero_values
FROM token_usage_log;

-- Quick check: Recent activity (last hour)
SELECT
    COUNT(*) as entries_last_hour,
    SUM(total_tokens) as tokens_last_hour,
    MAX(created_at) as latest_entry
FROM token_usage_log
WHERE created_at >= NOW() - INTERVAL '1 hour';