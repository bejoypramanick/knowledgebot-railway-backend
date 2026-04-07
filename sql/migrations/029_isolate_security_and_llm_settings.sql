-- ============================================================================
-- Isolate Security Settings and LLM Providers per Tenant
-- ============================================================================
-- This migration ensures that settings like HIL status, response timeout,
-- and LLM token limits are isolated per tenant.
-- ============================================================================

SET statement_timeout = '300s';
SET lock_timeout = '30s';

-- 1. Add tenant_id column to security_settings
ALTER TABLE public.security_settings ADD COLUMN IF NOT EXISTS tenant_id uuid;
UPDATE public.security_settings SET tenant_id = public.default_tenant_id() WHERE tenant_id IS NULL;
ALTER TABLE public.security_settings ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.security_settings ALTER COLUMN tenant_id SET NOT NULL;

-- 2. Add tenant_id column to llm_providers
ALTER TABLE public.llm_providers ADD COLUMN IF NOT EXISTS tenant_id uuid;
UPDATE public.llm_providers SET tenant_id = public.default_tenant_id() WHERE tenant_id IS NULL;
ALTER TABLE public.llm_providers ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.llm_providers ALTER COLUMN tenant_id SET NOT NULL;

-- 3. Update Unique Constraints
-- security_settings: setting_name -> (tenant_id, setting_name)
ALTER TABLE public.security_settings DROP CONSTRAINT IF EXISTS security_settings_setting_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_security_settings_tenant_name ON public.security_settings (tenant_id, setting_name);

-- llm_providers: provider_name -> (tenant_id, provider_name)
ALTER TABLE public.llm_providers DROP CONSTRAINT IF EXISTS llm_providers_provider_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_providers_tenant_name ON public.llm_providers (tenant_id, provider_name);

-- 4. Enable Row Level Security and add policies
ALTER TABLE public.security_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.security_settings FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS security_settings_select_policy ON public.security_settings;
CREATE POLICY security_settings_select_policy ON public.security_settings FOR SELECT USING (tenant_id = public.current_tenant_id_optional());

DROP POLICY IF EXISTS security_settings_insert_policy ON public.security_settings;
CREATE POLICY security_settings_insert_policy ON public.security_settings FOR INSERT WITH CHECK (tenant_id = public.current_tenant_id_optional());

DROP POLICY IF EXISTS security_settings_update_policy ON public.security_settings;
CREATE POLICY security_settings_update_policy ON public.security_settings FOR UPDATE USING (tenant_id = public.current_tenant_id_optional()) WITH CHECK (tenant_id = public.current_tenant_id_optional());

DROP POLICY IF EXISTS security_settings_delete_policy ON public.security_settings;
CREATE POLICY security_settings_delete_policy ON public.security_settings FOR DELETE USING (tenant_id = public.current_tenant_id_optional());

ALTER TABLE public.llm_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.llm_providers FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS llm_providers_select_policy ON public.llm_providers;
CREATE POLICY llm_providers_select_policy ON public.llm_providers FOR SELECT USING (tenant_id = public.current_tenant_id_optional());

DROP POLICY IF EXISTS llm_providers_insert_policy ON public.llm_providers;
CREATE POLICY llm_providers_insert_policy ON public.llm_providers FOR INSERT WITH CHECK (tenant_id = public.current_tenant_id_optional());

DROP POLICY IF EXISTS llm_providers_update_policy ON public.llm_providers;
CREATE POLICY llm_providers_update_policy ON public.llm_providers FOR UPDATE USING (tenant_id = public.current_tenant_id_optional()) WITH CHECK (tenant_id = public.current_tenant_id_optional());

DROP POLICY IF EXISTS llm_providers_delete_policy ON public.llm_providers;
CREATE POLICY llm_providers_delete_policy ON public.llm_providers FOR DELETE USING (tenant_id = public.current_tenant_id_optional());

-- 5. Update bootstrap_tenant_defaults to seed these tables
CREATE OR REPLACE FUNCTION public.bootstrap_tenant_defaults()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Seed widget configuration
    INSERT INTO public.widget_configuration (tenant_id, is_singleton)
    VALUES (NEW.id, true)
    ON CONFLICT DO NOTHING;

    -- Seed persona configurations
    INSERT INTO public.persona_configurations (
        tenant_id,
        persona_name,
        persona_description,
        system_prompt,
        is_active,
        created_at,
        updated_at
    )
    SELECT
        NEW.id,
        pc.persona_name,
        pc.persona_description,
        pc.system_prompt,
        pc.is_active,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM public.persona_configurations AS pc
    WHERE pc.tenant_id = public.default_tenant_id()
    ON CONFLICT DO NOTHING;

    -- Seed security settings
    INSERT INTO public.security_settings (
        tenant_id,
        setting_name,
        setting_value,
        setting_type,
        description,
        created_at,
        updated_at
    )
    SELECT
        NEW.id,
        ss.setting_name,
        ss.setting_value,
        ss.setting_type,
        ss.description,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM public.security_settings AS ss
    WHERE ss.tenant_id = public.default_tenant_id()
    ON CONFLICT DO NOTHING;

    -- Seed LLM providers
    INSERT INTO public.llm_providers (
        tenant_id,
        provider_name,
        token_limit,
        token_used,
        is_active,
        created_at,
        updated_at
    )
    SELECT
        NEW.id,
        lp.provider_name,
        lp.token_limit,
        0, -- Reset token usage for new tenant
        lp.is_active,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM public.llm_providers AS lp
    WHERE lp.tenant_id = public.default_tenant_id()
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;
