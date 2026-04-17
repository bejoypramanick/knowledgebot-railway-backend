-- Migration: 043_tenant_kb_quota_rls_policies
-- Description: Adds RLS policies for tenant_kb_quota tables to allow superadmins to bypass tenant checks.

DO $$
BEGIN
    -- tenant_kb_quota_config
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'tenant_kb_quota_config' AND schemaname = 'public') THEN
        RAISE NOTICE 'tenant_kb_quota_config table does not exist, skipping';
    ELSE
        -- Enable RLS only if not already enabled
        IF NOT (SELECT relrowsecurity FROM pg_class WHERE relname = 'tenant_kb_quota_config') THEN
            ALTER TABLE public.tenant_kb_quota_config ENABLE ROW LEVEL SECURITY;
        END IF;
        
        DROP POLICY IF EXISTS tenant_kb_quota_config_select_policy ON public.tenant_kb_quota_config;
        CREATE POLICY tenant_kb_quota_config_select_policy
        ON public.tenant_kb_quota_config
        FOR SELECT
        USING (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
        
        DROP POLICY IF EXISTS tenant_kb_quota_config_insert_policy ON public.tenant_kb_quota_config;
        CREATE POLICY tenant_kb_quota_config_insert_policy
        ON public.tenant_kb_quota_config
        FOR INSERT
        WITH CHECK (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
        
        DROP POLICY IF EXISTS tenant_kb_quota_config_update_policy ON public.tenant_kb_quota_config;
        CREATE POLICY tenant_kb_quota_config_update_policy
        ON public.tenant_kb_quota_config
        FOR UPDATE
        USING (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
    END IF;
    
    -- tenant_kb_quota_monthly_usage
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'tenant_kb_quota_monthly_usage' AND schemaname = 'public') THEN
        RAISE NOTICE 'tenant_kb_quota_monthly_usage table does not exist, skipping';
    ELSE
        -- Enable RLS only if not already enabled
        IF NOT (SELECT relrowsecurity FROM pg_class WHERE relname = 'tenant_kb_quota_monthly_usage') THEN
            ALTER TABLE public.tenant_kb_quota_monthly_usage ENABLE ROW LEVEL SECURITY;
        END IF;
        
        DROP POLICY IF EXISTS tenant_kb_quota_monthly_usage_select_policy ON public.tenant_kb_quota_monthly_usage;
        CREATE POLICY tenant_kb_quota_monthly_usage_select_policy
        ON public.tenant_kb_quota_monthly_usage
        FOR SELECT
        USING (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
        
        DROP POLICY IF EXISTS tenant_kb_quota_monthly_usage_insert_policy ON public.tenant_kb_quota_monthly_usage;
        CREATE POLICY tenant_kb_quota_monthly_usage_insert_policy
        ON public.tenant_kb_quota_monthly_usage
        FOR INSERT
        WITH CHECK (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
        
        DROP POLICY IF EXISTS tenant_kb_quota_monthly_usage_update_policy ON public.tenant_kb_quota_monthly_usage;
        CREATE POLICY tenant_kb_quota_monthly_usage_update_policy
        ON public.tenant_kb_quota_monthly_usage
        FOR UPDATE
        USING (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
    END IF;
    
    -- file_uploads: Add superadmin bypass policy for KB usage calculation
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'file_uploads' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS file_uploads_superadmin_bypass ON public.file_uploads;
        CREATE POLICY file_uploads_superadmin_bypass
        ON public.file_uploads
        FOR SELECT
        USING (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
    END IF;
    
    -- scraped_websites: Add superadmin bypass policy for KB usage calculation
    IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'scraped_websites' AND schemaname = 'public') THEN
        DROP POLICY IF EXISTS scraped_websites_superadmin_bypass ON public.scraped_websites;
        CREATE POLICY scraped_websites_superadmin_bypass
        ON public.scraped_websites
        FOR SELECT
        USING (
            public.is_superadmin()
            OR tenant_id = public.current_tenant_id_optional()
        );
    END IF;
    
    RAISE NOTICE 'Migration 043 completed: RLS policies created for tenant_kb_quota tables';
END $$;
