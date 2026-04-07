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

    -- Special handling for tenants to allow self-service provisioning
    DROP POLICY IF EXISTS tenants_write_policy ON public.tenants;
    DROP POLICY IF EXISTS tenants_insert_policy ON public.tenants;
    DROP POLICY IF EXISTS tenants_update_policy ON public.tenants;
    DROP POLICY IF EXISTS tenants_delete_policy ON public.tenants;

    -- Allow anyone to create a tenant, or at least any authorized user without a tenant context
    CREATE POLICY tenants_insert_policy ON public.tenants FOR INSERT WITH CHECK (true);
    CREATE POLICY tenants_update_policy ON public.tenants FOR UPDATE USING (id = public.current_tenant_id_optional()) WITH CHECK (id = public.current_tenant_id_optional());
    CREATE POLICY tenants_delete_policy ON public.tenants FOR DELETE USING (id = public.current_tenant_id_optional());

    -- Update tenants select policy to ensure the newly created tenant is visible during RETURNING
    -- even before the session context is updated with the new ID.
    DROP POLICY IF EXISTS tenants_select_policy ON public.tenants;
    CREATE POLICY tenants_select_policy ON public.tenants FOR SELECT USING (
        id = public.current_tenant_id_optional()
        OR (public.current_tenant_id_optional() IS NULL AND metadata->>'provisioned_for' = public.current_user_email_optional())
        OR EXISTS (
            SELECT 1
            FROM public.user_role_mapping AS urm
            JOIN public.users AS u ON u.id = urm.user_id
            WHERE urm.tenant_id = public.tenants.id
              AND urm.is_active = true
              AND u.email = public.current_user_email_optional()
        )
    );

END $$;
