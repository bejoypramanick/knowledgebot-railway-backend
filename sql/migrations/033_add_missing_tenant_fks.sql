-- ============================================================================
-- Add Missing Tenant Foreign Keys
-- ============================================================================
-- security_settings and llm_providers were tenant-scoped in migration 029,
-- but they were missing the actual foreign key back to public.tenants(id).
-- This closes that integrity gap.
-- ============================================================================

DO $$
BEGIN
    BEGIN
        ALTER TABLE public.security_settings
            ADD CONSTRAINT security_settings_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;

    BEGIN
        ALTER TABLE public.llm_providers
            ADD CONSTRAINT llm_providers_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END $$;
