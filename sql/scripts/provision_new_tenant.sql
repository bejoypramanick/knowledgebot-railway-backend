-- ============================================================================
-- New Tenant Provisioning Script
-- ============================================================================
-- Creates a fully-provisioned tenant with:
--   • A new row in public.tenants  (name = random element + number, e.g. "Neon-42")
--   • Default widget_configuration (via bootstrap_tenant_defaults trigger)
--   • Default persona_configurations (cloned from bootstrap tenant)
--   • Default security_settings     (cloned from bootstrap tenant)
--   • Default llm_providers         (cloned from bootstrap tenant)
--   • A user row in public.users    (created if email does not exist yet)
--   • An admin role mapping         (M2M — user can be admin on multiple tenants)
--   • Notification settings for the admin email
--
-- USAGE:
--   Edit v_admin_email below, then run:
--       psql "$DATABASE_URL" -f sql/scripts/provision_new_tenant.sql
-- ============================================================================

DO $$
DECLARE
    -- ----------------------------------------------------------------
    -- ✏️  ONLY THIS ONE VALUE NEEDS TO BE SET
    -- ----------------------------------------------------------------
    v_admin_email   TEXT := 'admin@example.com';   -- ← admin's Google / email
    -- ----------------------------------------------------------------

    -- Internal working vars
    v_elements      TEXT[] := ARRAY[
        'Hydrogen','Helium','Lithium','Beryllium','Boron','Carbon','Nitrogen',
        'Oxygen','Fluorine','Neon','Sodium','Magnesium','Aluminium','Silicon',
        'Phosphorus','Sulfur','Chlorine','Argon','Potassium','Calcium','Scandium',
        'Titanium','Vanadium','Chromium','Manganese','Iron','Cobalt','Nickel',
        'Copper','Zinc','Gallium','Germanium','Arsenic','Selenium','Bromine',
        'Krypton','Rubidium','Strontium','Yttrium','Zirconium','Niobium',
        'Molybdenum','Technetium','Ruthenium','Rhodium','Palladium','Silver',
        'Cadmium','Indium','Tin','Antimony','Tellurium','Iodine','Xenon',
        'Caesium','Barium','Lanthanum','Cerium','Praseodymium','Neodymium',
        'Promethium','Samarium','Europium','Gadolinium','Terbium','Dysprosium',
        'Holmium','Erbium','Thulium','Ytterbium','Lutetium','Hafnium','Tantalum',
        'Tungsten','Rhenium','Osmium','Iridium','Platinum','Gold','Mercury',
        'Thallium','Lead','Bismuth','Polonium','Astatine','Radon','Francium',
        'Radium','Actinium','Thorium','Protactinium','Uranium','Neptunium',
        'Plutonium','Americium','Curium','Berkelium','Californium','Einsteinium',
        'Fermium','Mendelevium','Nobelium','Lawrencium','Rutherfordium',
        'Dubnium','Seaborgium','Bohrium','Hassium','Meitnerium','Darmstadtium',
        'Roentgenium','Copernicium','Nihonium','Flerovium','Moscovium',
        'Livermorium','Tennessine','Oganesson'
    ];

    v_element       TEXT;
    v_number        INT;
    v_tenant_name   TEXT;
    v_tenant_slug   TEXT;
    v_tenant_id     UUID;
    v_user_id       UUID;
    v_admin_role_id UUID;
    v_user_role_id  UUID;
    v_attempt       INT := 0;
BEGIN
    -- ----------------------------------------------------------------
    -- 0a. Pick a unique element-number combination for the tenant name.
    --
    -- Collision math:
    --   118 elements × 9999 numbers = ~1,179,882 total combinations.
    --   At   10,000 tenants  →  ~0.8% collision rate  → avg 1.008 attempts
    --   At  100,000 tenants  →  ~8.5% collision rate  → avg 1.09  attempts
    --   At  500,000 tenants  →  ~42%  collision rate  → avg 1.7   attempts
    --   At 1,000,000 tenants →  ~85%  collision rate  → avg ~7    attempts
    --
    -- The retry cap is 50 — far above what is ever needed in practice.
    -- ----------------------------------------------------------------
    LOOP
        v_attempt := v_attempt + 1;
        IF v_attempt > 50 THEN
            RAISE EXCEPTION 'Could not generate a unique tenant name after 50 attempts — the combination space may be exhausted or something is wrong.';
        END IF;

        -- Random element from the array
        v_element     := v_elements[ 1 + floor(random() * array_length(v_elements, 1))::int ];
        -- Random number 1–999
        v_number      := 1 + floor(random() * 9999)::int;  -- 1–9999 → ~1.18 M combinations

        v_tenant_name := v_element || '-' || v_number;                      -- e.g. "Neon-42"
        v_tenant_slug := lower(v_element) || '-' || v_number;               -- e.g. "neon-42"

        EXIT WHEN NOT EXISTS (
            SELECT 1 FROM public.tenants
            WHERE slug = v_tenant_slug OR name = v_tenant_name
        );
    END LOOP;

    RAISE NOTICE '🎲 Generated tenant identity: % (slug: %)', v_tenant_name, v_tenant_slug;

    -- ----------------------------------------------------------------
    -- 0b. M2M notice: same admin can belong to multiple tenants
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
    --    The AFTER INSERT trigger `bootstrap_tenant_defaults` fires here
    --    and seeds: widget_configuration, persona_configurations,
    --    security_settings, llm_providers
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

    RAISE NOTICE '✅ Tenant created: % (id=%)', v_tenant_name, v_tenant_id;

    -- ----------------------------------------------------------------
    -- 2. Upsert the user (create if they don't exist yet)
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
        RAISE EXCEPTION 'No role named "admin" found in public.roles. Check your roles table.';
    END IF;

    -- ----------------------------------------------------------------
    -- 4. Create the user_role_mapping (admin → new tenant)
    --    ON CONFLICT uses column list because unique key is an INDEX,
    --    not a named CONSTRAINT.
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
    -- 5. Seed notification_settings for the admin
    -- ----------------------------------------------------------------
    INSERT INTO public.notification_settings (
        tenant_id, user_email,
        notify_new_chat, notify_human_request, notify_feedback,
        created_at, updated_at
    )
    VALUES (
        v_tenant_id, v_admin_email,
        true, true, true,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
    )
    ON CONFLICT DO NOTHING;

    RAISE NOTICE '✅ Notification settings seeded for %', v_admin_email;

    -- ----------------------------------------------------------------
    -- 6. Summary
    -- ----------------------------------------------------------------
    RAISE NOTICE '';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '  NEW TENANT PROVISIONED SUCCESSFULLY';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '  Tenant Name  : %', v_tenant_name;
    RAISE NOTICE '  Tenant Slug  : %', v_tenant_slug;
    RAISE NOTICE '  Tenant ID    : %', v_tenant_id;
    RAISE NOTICE '  Admin Email  : %', v_admin_email;
    RAISE NOTICE '  Admin User ID: %', v_user_id;
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  • Send the admin a sign-in link / password reset.';
    RAISE NOTICE '  • Pass X-Tenant-ID: % in API calls for this tenant.', v_tenant_id;

END $$;
