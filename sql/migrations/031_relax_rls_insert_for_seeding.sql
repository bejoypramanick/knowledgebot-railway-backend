-- ============================================================================
-- Relax RLS Insert Policies for Seeding and Provisioning
-- ============================================================================
-- This migration updates RLS policies to allow INSERT operations when no
-- tenant context is set (app.current_tenant_id is NULL).
-- This is required for:
-- 1. Initial system seeding of the default tenant.
-- 2. Automatic provisioning of defaults for new tenants.
-- ============================================================================

DO $$
DECLARE
    tenant_table text;
BEGIN
    -- General loop for most tables
    FOREACH tenant_table IN ARRAY ARRAY[
        'admin_sessions',
        'admin_actions',
        'api_usage',
        'notification_settings',
        'notifications',
        'persona_configurations',
        'widget_configuration',
        'widget_suggested_messages',
        'chat_sessions',
        'chat_messages',
        'file_uploads',
        'scraped_websites',
        'session_assignments',
        'tables_metadata',
        'agent_run_steps',
        'token_usage_log',
        'document_chunks',
        'security_settings',
        'llm_providers'
    ]
    LOOP
        -- Relax INSERT policy: allow if no context is set OR if it matches context
        EXECUTE format('DROP POLICY IF EXISTS %I_insert_policy ON public.%I', tenant_table, tenant_table);
        EXECUTE format('DROP POLICY IF EXISTS %I_write_policy ON public.%I', tenant_table, tenant_table);
        
        EXECUTE format(
            'CREATE POLICY %s_insert_policy ON public.%I FOR INSERT WITH CHECK (tenant_id = COALESCE(public.current_tenant_id_optional(), tenant_id))',
            tenant_table,
            tenant_table
        );
    END LOOP;

    -- Special handling for user_role_mapping to ensure all policies are clean
    DROP POLICY IF EXISTS user_role_mapping_write_policy ON public.user_role_mapping;
    DROP POLICY IF EXISTS user_role_mapping_insert_policy ON public.user_role_mapping;
    DROP POLICY IF EXISTS user_role_mapping_update_policy ON public.user_role_mapping;
    DROP POLICY IF EXISTS user_role_mapping_delete_policy ON public.user_role_mapping;

    CREATE POLICY user_role_mapping_insert_policy ON public.user_role_mapping FOR INSERT WITH CHECK (tenant_id = COALESCE(public.current_tenant_id_optional(), tenant_id));
    CREATE POLICY user_role_mapping_update_policy ON public.user_role_mapping FOR UPDATE USING (tenant_id = public.current_tenant_id_optional()) WITH CHECK (tenant_id = public.current_tenant_id_optional());
    CREATE POLICY user_role_mapping_delete_policy ON public.user_role_mapping FOR DELETE USING (tenant_id = public.current_tenant_id_optional());

END $$;
