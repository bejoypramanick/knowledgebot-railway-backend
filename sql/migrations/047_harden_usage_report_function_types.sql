-- Migration: 047_harden_usage_report_function_types
-- Description:
--   Recreate usage report SECURITY DEFINER helpers with explicit casts and
--   corrected return types. Older deployments can fail with
--   "structure of query does not match function result type" when the helper
--   signature drifts from the actual table column types.

DO $$
DECLARE
    func_record RECORD;
BEGIN
    FOR func_record IN
        SELECT oid::regprocedure AS func
        FROM pg_proc
        WHERE proname IN ('get_usage_sessions', 'get_usage_files', 'get_usage_websites', 'get_usage_token_log')
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
        cs.id::UUID,
        cs.tenant_id::UUID,
        cs.started_at::TIMESTAMPTZ,
        cs.last_activity_at::TIMESTAMPTZ,
        cs.message_count::INTEGER,
        cs.total_character_count::INTEGER,
        cs.total_word_count::INTEGER,
        cs.total_token_count::INTEGER,
        cs.total_message_token_count::INTEGER,
        cs.total_prompt_token_count::INTEGER,
        cs.total_completion_token_count::INTEGER,
        cs.total_system_prompt_token_count::INTEGER,
        cs.total_history_token_count::INTEGER,
        cs.total_tool_def_token_count::INTEGER,
        cs.total_user_msg_token_count::INTEGER,
        cs.total_bot_response_token_count::INTEGER,
        cs.archive_status::VARCHAR,
        cs.sentiment::VARCHAR,
        cs.duration_minutes::NUMERIC,
        cs.created_at::TIMESTAMPTZ
    FROM public.chat_sessions cs
    WHERE cs.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR cs.tenant_id = p_tenant_id)
    ORDER BY cs.created_at DESC;
END;
$$;

CREATE FUNCTION public.get_usage_files(
    p_tenant_id UUID DEFAULT NULL,
    p_since TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    original_filename VARCHAR,
    display_name VARCHAR,
    file_extension VARCHAR,
    processing_status VARCHAR,
    file_size BIGINT,
    char_count INTEGER,
    embedding_character_count INTEGER,
    embedding_word_count INTEGER,
    embedding_token_count INTEGER,
    processed_by_extractor BOOLEAN,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        fu.id::UUID,
        fu.tenant_id::UUID,
        fu.original_filename::VARCHAR,
        fu.display_name::VARCHAR,
        fu.file_extension::VARCHAR,
        fu.processing_status::VARCHAR,
        fu.file_size::BIGINT,
        fu.char_count::INTEGER,
        fu.embedding_character_count::INTEGER,
        fu.embedding_word_count::INTEGER,
        fu.embedding_token_count::INTEGER,
        fu.processed_by_extractor::BOOLEAN,
        fu.created_at::TIMESTAMPTZ
    FROM public.file_uploads fu
    WHERE fu.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR fu.tenant_id = p_tenant_id)
    ORDER BY fu.created_at DESC;
END;
$$;

CREATE FUNCTION public.get_usage_websites(
    p_tenant_id UUID DEFAULT NULL,
    p_since TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    original_url TEXT,
    title VARCHAR,
    processing_status VARCHAR,
    pages_scraped INTEGER,
    file_size INTEGER,
    char_count INTEGER,
    embedding_character_count INTEGER,
    embedding_word_count INTEGER,
    embedding_token_count INTEGER,
    parent_id UUID,
    depth INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        sw.id::UUID,
        sw.tenant_id::UUID,
        sw.original_url::TEXT,
        sw.title::VARCHAR,
        sw.processing_status::VARCHAR,
        sw.pages_scraped::INTEGER,
        sw.file_size::INTEGER,
        sw.char_count::INTEGER,
        sw.embedding_character_count::INTEGER,
        sw.embedding_word_count::INTEGER,
        sw.embedding_token_count::INTEGER,
        sw.parent_id::UUID,
        sw.depth::INTEGER,
        sw.created_at::TIMESTAMPTZ
    FROM public.scraped_websites sw
    WHERE sw.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR sw.tenant_id = p_tenant_id)
    ORDER BY sw.created_at DESC;
END;
$$;

CREATE FUNCTION public.get_usage_token_log(
    p_tenant_id UUID DEFAULT NULL,
    p_since TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    session_id UUID,
    created_at TIMESTAMPTZ,
    total_tokens INTEGER,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    model VARCHAR,
    request_metadata JSONB
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT
        tul.id::UUID,
        tul.tenant_id::UUID,
        tul.session_id::UUID,
        tul.created_at::TIMESTAMPTZ,
        tul.total_tokens::INTEGER,
        tul.prompt_tokens::INTEGER,
        tul.completion_tokens::INTEGER,
        tul.model::VARCHAR,
        tul.request_metadata::JSONB
    FROM public.token_usage_log tul
    WHERE tul.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR tul.tenant_id = p_tenant_id)
    ORDER BY tul.created_at DESC;
END;
$$;

COMMENT ON FUNCTION public.get_usage_sessions(UUID, TIMESTAMPTZ)
IS 'Bypasses RLS to fetch chat_sessions for usage report with explicit result type casts.';

COMMENT ON FUNCTION public.get_usage_files(UUID, TIMESTAMPTZ)
IS 'Bypasses RLS to fetch file_uploads for usage report; file_size is BIGINT and processed_by_extractor is BOOLEAN.';

COMMENT ON FUNCTION public.get_usage_websites(UUID, TIMESTAMPTZ)
IS 'Bypasses RLS to fetch scraped_websites for usage report with explicit result type casts.';

COMMENT ON FUNCTION public.get_usage_token_log(UUID, TIMESTAMPTZ)
IS 'Bypasses RLS to fetch token_usage_log for usage report with explicit result type casts.';
