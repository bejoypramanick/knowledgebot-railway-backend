-- Migration: 046_fix_usage_sessions_duration_minutes_type
-- Description:
--   Recreate get_usage_sessions with duration_minutes declared as NUMERIC.
--   Some deployed databases still have an older INTEGER-returning function
--   even though chat_sessions.duration_minutes is a NUMERIC generated column.

DO $$
DECLARE
    func_record RECORD;
BEGIN
    FOR func_record IN
        SELECT oid::regprocedure AS func
        FROM pg_proc
        WHERE proname = 'get_usage_sessions'
          AND pronamespace = 'public'::regnamespace
    LOOP
        EXECUTE 'DROP FUNCTION IF EXISTS ' || func_record.func || ' CASCADE';
    END LOOP;
END $$;

CREATE FUNCTION public.get_usage_sessions(
    p_tenant_id UUID DEFAULT NULL,
    p_since TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    started_at TIMESTAMPTZ,
    last_activity_at TIMESTAMPTZ,
    message_count INTEGER,
    total_character_count INTEGER,
    total_word_count INTEGER,
    total_token_count INTEGER,
    total_message_token_count INTEGER,
    total_prompt_token_count INTEGER,
    total_completion_token_count INTEGER,
    total_system_prompt_token_count INTEGER,
    total_history_token_count INTEGER,
    total_tool_def_token_count INTEGER,
    total_user_msg_token_count INTEGER,
    total_bot_response_token_count INTEGER,
    archive_status VARCHAR,
    sentiment VARCHAR,
    duration_minutes NUMERIC,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        cs.id,
        cs.tenant_id,
        cs.started_at,
        cs.last_activity_at,
        cs.message_count,
        cs.total_character_count,
        cs.total_word_count,
        cs.total_token_count,
        cs.total_message_token_count,
        cs.total_prompt_token_count,
        cs.total_completion_token_count,
        cs.total_system_prompt_token_count,
        cs.total_history_token_count,
        cs.total_tool_def_token_count,
        cs.total_user_msg_token_count,
        cs.total_bot_response_token_count,
        cs.archive_status,
        cs.sentiment,
        cs.duration_minutes::NUMERIC,
        cs.created_at
    FROM public.chat_sessions cs
    WHERE cs.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR cs.tenant_id = p_tenant_id)
    ORDER BY cs.created_at DESC;
END;
$$;

COMMENT ON FUNCTION public.get_usage_sessions(UUID, TIMESTAMPTZ)
IS 'Bypasses RLS to fetch chat_sessions for usage report; duration_minutes is NUMERIC.';
