-- Migration: 045_usage_report_bypass_rls
-- Description: Create a function to bypass RLS for usage report queries

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

CREATE FUNCTION public.get_usage_sessions(p_tenant_id UUID DEFAULT NULL, p_since TIMESTAMPTZ DEFAULT NULL)
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
    duration_minutes INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT cs.id, cs.tenant_id, cs.started_at, cs.last_activity_at, cs.message_count,
           cs.total_character_count, cs.total_word_count, cs.total_token_count,
           cs.total_message_token_count, cs.total_prompt_token_count, cs.total_completion_token_count,
           cs.total_system_prompt_token_count, cs.total_history_token_count,
           cs.total_tool_def_token_count, cs.total_user_msg_token_count, cs.total_bot_response_token_count,
           cs.archive_status, cs.sentiment, cs.duration_minutes, cs.created_at
    FROM public.chat_sessions cs
    WHERE cs.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR cs.tenant_id = p_tenant_id)
    ORDER BY cs.created_at DESC;
END;
$$;

CREATE FUNCTION public.get_usage_files(p_tenant_id UUID DEFAULT NULL, p_since TIMESTAMPTZ DEFAULT NULL)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    original_filename VARCHAR,
    display_name VARCHAR,
    file_extension VARCHAR,
    processing_status VARCHAR,
    file_size INTEGER,
    char_count INTEGER,
    filestore_character_count INTEGER,
    filestore_word_count INTEGER,
    filestore_token_count INTEGER,
    processed_by_extractor VARCHAR,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT fu.id, fu.tenant_id, fu.original_filename, fu.display_name, fu.file_extension, fu.processing_status,
           fu.file_size, fu.char_count,
           fu.filestore_character_count, fu.filestore_word_count, fu.filestore_token_count,
           fu.processed_by_extractor, fu.created_at
    FROM public.file_uploads fu
    WHERE fu.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR fu.tenant_id = p_tenant_id)
    ORDER BY fu.created_at DESC;
END;
$$;

CREATE FUNCTION public.get_usage_websites(p_tenant_id UUID DEFAULT NULL, p_since TIMESTAMPTZ DEFAULT NULL)
RETURNS TABLE (
    id UUID,
    tenant_id UUID,
    original_url TEXT,
    title VARCHAR,
    processing_status VARCHAR,
    pages_scraped INTEGER,
    file_size INTEGER,
    char_count INTEGER,
    filestore_character_count INTEGER,
    filestore_word_count INTEGER,
    filestore_token_count INTEGER,
    parent_id UUID,
    depth INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT sw.id, sw.tenant_id, sw.original_url, sw.title, sw.processing_status, sw.pages_scraped,
           sw.file_size, sw.char_count,
           sw.filestore_character_count, sw.filestore_word_count, sw.filestore_token_count,
           sw.parent_id, sw.depth, sw.created_at
    FROM public.scraped_websites sw
    WHERE sw.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR sw.tenant_id = p_tenant_id)
    ORDER BY sw.created_at DESC;
END;
$$;

-- Also create function for token_usage_log
CREATE FUNCTION public.get_usage_token_log(p_tenant_id UUID DEFAULT NULL, p_since TIMESTAMPTZ DEFAULT NULL)
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
    SELECT tul.id, tul.tenant_id, tul.session_id, tul.created_at, tul.total_tokens,
           tul.prompt_tokens, tul.completion_tokens, tul.model, tul.request_metadata
    FROM public.token_usage_log tul
    WHERE tul.created_at >= COALESCE(p_since, NOW() - INTERVAL '365 days')
      AND (p_tenant_id IS NULL OR tul.tenant_id = p_tenant_id)
    ORDER BY tul.created_at DESC;
END;
$$;

COMMENT ON FUNCTION public.get_usage_sessions IS 'Bypasses RLS to fetch chat_sessions for usage report';
COMMENT ON FUNCTION public.get_usage_files IS 'Bypasses RLS to fetch file_uploads for usage report';
COMMENT ON FUNCTION public.get_usage_websites IS 'Bypasses RLS to fetch scraped_websites for usage report';
COMMENT ON FUNCTION public.get_usage_token_log IS 'Bypasses RLS to fetch token_usage_log for usage report';