-- Migration: 044_usage_report_rls_bypass
-- Description: Adds RLS superadmin bypass policies for usage report tables.
-- This allows superadmins to see all tenant data in the usage report.

DO $$
BEGIN
    -- chat_sessions: Add superadmin bypass for SELECT
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'chat_sessions' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS chat_sessions_superadmin_select ON public.chat_sessions;
        CREATE POLICY chat_sessions_superadmin_select
        ON public.chat_sessions
        FOR SELECT
        USING (public.is_superadmin() OR tenant_id = public.current_tenant_id_optional());
        RAISE NOTICE 'Created chat_sessions superadmin bypass policy';
    END IF;

    -- chat_messages: Add superadmin bypass for SELECT
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'chat_messages' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS chat_messages_superadmin_select ON public.chat_messages;
        CREATE POLICY chat_messages_superadmin_select
        ON public.chat_messages
        FOR SELECT
        USING (public.is_superadmin() OR tenant_id = public.current_tenant_id_optional());
        RAISE NOTICE 'Created chat_messages superadmin bypass policy';
    END IF;

    -- token_usage_log: Add superadmin bypass for SELECT
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'token_usage_log' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS token_usage_log_superadmin_select ON public.token_usage_log;
        CREATE POLICY token_usage_log_superadmin_select
        ON public.token_usage_log
        FOR SELECT
        USING (public.is_superadmin() OR tenant_id = public.current_tenant_id_optional());
        RAISE NOTICE 'Created token_usage_log superadmin bypass policy';
    END IF;

    -- agent_run_steps: Add superadmin bypass for SELECT
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'agent_run_steps' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS agent_run_steps_superadmin_select ON public.agent_run_steps;
        CREATE POLICY agent_run_steps_superadmin_select
        ON public.agent_run_steps
        FOR SELECT
        USING (public.is_superadmin() OR tenant_id = public.current_tenant_id_optional());
        RAISE NOTICE 'Created agent_run_steps superadmin bypass policy';
    END IF;

    -- document_chunks: Add superadmin bypass for SELECT
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'document_chunks' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS document_chunks_superadmin_select ON public.document_chunks;
        CREATE POLICY document_chunks_superadmin_select
        ON public.document_chunks
        FOR SELECT
        USING (public.is_superadmin() OR tenant_id = public.current_tenant_id_optional());
        RAISE NOTICE 'Created document_chunks superadmin bypass policy';
    END IF;

    RAISE NOTICE 'Migration 044 completed: Created superadmin bypass RLS policies for usage report tables';
END $$;