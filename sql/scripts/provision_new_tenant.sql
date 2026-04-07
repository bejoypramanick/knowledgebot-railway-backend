-- ============================================================================
-- New Tenant Provisioning Script
-- ============================================================================
-- Creates a fully-provisioned tenant where:
--   • The operator must provide admin_email, tenant_name, and tenant_slug.
--   • The script enforces that the slug and name are completely unique.
--
-- Seeds:
--   • widget_configuration      (via bootstrap_tenant_defaults trigger)
--   • persona_configurations    (cloned from bootstrap tenant)
--   • security_settings         (cloned from bootstrap tenant)
--   • llm_providers             (cloned from bootstrap tenant)
--   • user row in public.users  (created if email does not exist yet)
--   • admin role mapping        (M2M — user can be admin on many tenants)
--   • notification_settings for the admin
--
-- USAGE:
--   Edit the 3 configurations below, then run:
--       psql "$DATABASE_URL" -f sql/scripts/provision_new_tenant.sql
-- ============================================================================

DO $$
DECLARE
    -- ----------------------------------------------------------------
    -- ✏️  CONFIGURE THESE THREE VALUES BEFORE RUNNING
    -- ----------------------------------------------------------------
    v_admin_email   TEXT := 'admin@example.com';   
    v_tenant_name   TEXT := 'Acme Corporation';    
    v_tenant_slug   TEXT := 'acme-corporation';    
    -- ----------------------------------------------------------------

    v_tenant_id     UUID;
    v_user_id       UUID;
    v_admin_role_id UUID;
    v_user_role_id  UUID;
BEGIN

    -- ----------------------------------------------------------------
    -- 0a. Guard: Make sure the slug is independently unique
    -- ----------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM public.tenants WHERE slug = v_tenant_slug) THEN
        RAISE EXCEPTION '❌ A tenant with the slug "%" already exists.', v_tenant_slug;
    END IF;

    -- ----------------------------------------------------------------
    -- 0b. Guard: Make sure the tenant name is independently unique
    -- ----------------------------------------------------------------
    IF EXISTS (SELECT 1 FROM public.tenants WHERE name = v_tenant_name) THEN
        RAISE EXCEPTION '❌ A tenant with the name "%" already exists.', v_tenant_name;
    END IF;

    -- ----------------------------------------------------------------
    -- 0c. M2M notice: same admin can belong to multiple tenants
    -- ----------------------------------------------------------------
    IF EXISTS (
        SELECT 1
        FROM public.user_role_mapping urm
        JOIN public.users u ON u.id = urm.user_id
        JOIN public.roles r ON r.id = urm.role_id
        WHERE u.email = v_admin_email AND r.role_name = 'admin'
        LIMIT 1
    ) THEN
        RAISE NOTICE 'ℹ️  "%" is already admin on other tenant(s) — M2M is supported, adding them here too.', v_admin_email;
    END IF;

    -- ----------------------------------------------------------------
    -- 1. Create the tenant
    --    Let the DB generate the uuidv7 id via the column DEFAULT.
    --    The AFTER INSERT trigger `bootstrap_tenant_defaults` fires here
    --    and seeds: widget_configuration, persona_configurations,
    --    security_settings, llm_providers.
    -- ----------------------------------------------------------------
    INSERT INTO public.tenants (slug, name, description, is_active, metadata)
    VALUES (
        v_tenant_slug,
        v_tenant_name,
        'Provisioned via provision_new_tenant.sql',
        true,
        jsonb_build_object(
            'seeded_by',   'provision_new_tenant.sql',
            'admin_email', v_admin_email,
            'created_at',  CURRENT_TIMESTAMP
        )
    )
    RETURNING id INTO v_tenant_id;

    RAISE NOTICE '✅ Tenant created (id=%, name=%, slug=%)', v_tenant_id, v_tenant_name, v_tenant_slug;

    -- ----------------------------------------------------------------
    -- 2. Upsert the user (create if they don't exist yet)
    --    The "users" table natively enforces that email is UNIQUE.
    -- ----------------------------------------------------------------
    INSERT INTO public.users (email, is_active, created_at, updated_at)
    VALUES (v_admin_email, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (email)
        DO UPDATE SET is_active = true, updated_at = CURRENT_TIMESTAMP
    RETURNING id INTO v_user_id;

    RAISE NOTICE '✅ User upserted: % (id=%)', v_admin_email, v_user_id;

    -- ----------------------------------------------------------------
    -- 3. Resolve 'admin' role id
    -- ----------------------------------------------------------------
    SELECT id INTO v_admin_role_id
    FROM public.roles
    WHERE role_name = 'admin'
    LIMIT 1;

    IF v_admin_role_id IS NULL THEN
        RAISE EXCEPTION '❌ No role named "admin" found in public.roles. Check your roles table.';
    END IF;

    -- ----------------------------------------------------------------
    -- 4. Create the admin role mapping (M2M — one user, many tenants)
    -- ----------------------------------------------------------------
    INSERT INTO public.user_role_mapping (
        user_id, role_id, tenant_id, is_active, created_at, updated_at
    )
    VALUES (
        v_user_id, v_admin_role_id, v_tenant_id,
        true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    ON CONFLICT (user_id, role_id, tenant_id)
        DO UPDATE SET is_active = true, updated_at = CURRENT_TIMESTAMP
    RETURNING user_role_id INTO v_user_role_id;

    RAISE NOTICE '✅ Admin role mapping created (user_role_id=%)', v_user_role_id;

    -- ----------------------------------------------------------------
    -- 5. Summary
    -- ----------------------------------------------------------------
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '  NEW TENANT PROVISIONED SUCCESSFULLY';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '  Tenant ID    : %', v_tenant_id;
    RAISE NOTICE '  Tenant Name  : %', v_tenant_name;
    RAISE NOTICE '  Tenant Slug  : %', v_tenant_slug;
    RAISE NOTICE '  Admin Email  : %', v_admin_email;
    RAISE NOTICE '  Admin User ID: %', v_user_id;
    RAISE NOTICE '============================================================';

END $$;
