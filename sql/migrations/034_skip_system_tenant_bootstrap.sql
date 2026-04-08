-- ============================================================================
-- Skip default seeding for the system tenant
-- ============================================================================
-- The system tenant is only used to anchor global superadmin memberships.
-- It should not receive tenant-scoped defaults such as personas, widget
-- configuration, security settings, or LLM provider rows.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.bootstrap_tenant_defaults()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.slug = 'system' THEN
        RETURN NEW;
    END IF;

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
        0,
        lp.is_active,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    FROM public.llm_providers AS lp
    WHERE lp.tenant_id = public.default_tenant_id()
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;
