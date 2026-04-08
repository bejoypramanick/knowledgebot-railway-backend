-- ============================================================================
-- Fix Tenant Persona Bootstrap Under RLS
-- ============================================================================
-- New tenant provisioning seeds defaults via bootstrap_tenant_defaults().
-- That trigger can run without app.current_tenant_id set, so invoker-mode RLS
-- may hide the default tenant's persona rows and result in zero personas being
-- copied for the new tenant.
--
-- This migration:
-- 1. Recreates bootstrap_tenant_defaults() as SECURITY DEFINER so it can seed
--    from the default tenant deterministically.
-- 2. Re-binds the tenant bootstrap trigger.
-- 3. Backfills any tenants that are missing persona rows.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.bootstrap_tenant_defaults()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.widget_configuration (tenant_id, is_singleton)
    VALUES (NEW.id, true)
    ON CONFLICT DO NOTHING;

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
    ON CONFLICT (tenant_id, persona_name) DO NOTHING;

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
    ON CONFLICT (tenant_id, setting_name) DO NOTHING;

    INSERT INTO public.llm_providers (
        tenant_id,
        provider_name,
        token_limit,
        token_used,
        monthly_token_budget,
        current_month_start,
        alert_80_percent_sent,
        alert_100_percent_sent,
        created_at,
        updated_at
    )
    SELECT
        NEW.id,
        lp.provider_name,
        lp.token_limit,
        0,
        lp.monthly_token_budget,
        lp.current_month_start,
        false,
        false,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM public.llm_providers AS lp
    WHERE lp.tenant_id = public.default_tenant_id()
    ON CONFLICT (tenant_id, provider_name) DO NOTHING;

    RETURN NEW;
END;
$$;

ALTER FUNCTION public.bootstrap_tenant_defaults() OWNER TO postgres;

DROP TRIGGER IF EXISTS tenants_bootstrap_defaults_trigger ON public.tenants;
CREATE TRIGGER tenants_bootstrap_defaults_trigger
AFTER INSERT ON public.tenants
FOR EACH ROW EXECUTE FUNCTION public.bootstrap_tenant_defaults();

-- Backfill personas for any tenant that missed them during provisioning.
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
    t.id,
    pc.persona_name,
    pc.persona_description,
    pc.system_prompt,
    pc.is_active,
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
FROM public.tenants AS t
JOIN public.persona_configurations AS pc
    ON pc.tenant_id = public.default_tenant_id()
LEFT JOIN public.persona_configurations AS existing
    ON existing.tenant_id = t.id
   AND existing.persona_name = pc.persona_name
WHERE t.id <> public.default_tenant_id()
  AND existing.id IS NULL
ON CONFLICT (tenant_id, persona_name) DO NOTHING;
