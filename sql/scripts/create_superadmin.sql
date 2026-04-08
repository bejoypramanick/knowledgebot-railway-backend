-- ============================================================================
-- Create or Upsert a Global Superadmin User
-- ============================================================================
-- Usage:
--   1. Replace the email value in v_superadmin_email below.
--   2. Run this script.
--
-- Behavior:
--   - Ensures the "superadmin" role exists.
--   - Ensures a system tenant exists, using PostgreSQL's default uuidv7().
--   - Ensures the given email exists in public.users.
--   - Ensures a user_role_mapping row exists for:
--       (user, superadmin role, system tenant)
--
-- Idempotent:
--   - Safe to run multiple times for the same email.
--   - Safe to run again later with a different email.
-- ============================================================================

DO $$
DECLARE
    v_superadmin_email text := 'replace-me@example.com';
    v_superadmin_role_id uuid;
    v_superadmin_user_id uuid;
    v_system_tenant_id uuid;
BEGIN
    IF v_superadmin_email IS NULL OR btrim(v_superadmin_email) = '' THEN
        RAISE EXCEPTION 'v_superadmin_email must be set before running this script';
    END IF;

    v_superadmin_email := lower(btrim(v_superadmin_email));

    INSERT INTO public.roles (role_name, role_description)
    VALUES ('superadmin', 'Platform-level super administrator')
    ON CONFLICT (role_name) DO UPDATE
    SET role_description = EXCLUDED.role_description,
        updated_at = CURRENT_TIMESTAMP;

    SELECT id
    INTO v_superadmin_role_id
    FROM public.roles
    WHERE role_name = 'superadmin';

    INSERT INTO public.tenants (slug, name, description, is_active, metadata)
    VALUES (
        'system',
        'System Tenant',
        'Global platform tenant for system-level roles such as superadmin.',
        true,
        '{"seeded_by":"create_superadmin.sql"}'::jsonb
    )
    ON CONFLICT (slug) DO UPDATE
    SET name = EXCLUDED.name,
        description = EXCLUDED.description,
        is_active = true,
        metadata = COALESCE(public.tenants.metadata, '{}'::jsonb) || EXCLUDED.metadata,
        updated_at = CURRENT_TIMESTAMP
    RETURNING id
    INTO v_system_tenant_id;

    IF v_system_tenant_id IS NULL THEN
        SELECT id
        INTO v_system_tenant_id
        FROM public.tenants
        WHERE slug = 'system';
    END IF;

    INSERT INTO public.users (email, is_active, created_at, updated_at)
    VALUES (v_superadmin_email, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (email) DO UPDATE
    SET is_active = true,
        updated_at = CURRENT_TIMESTAMP
    RETURNING id
    INTO v_superadmin_user_id;

    IF v_superadmin_user_id IS NULL THEN
        SELECT id
        INTO v_superadmin_user_id
        FROM public.users
        WHERE email = v_superadmin_email;
    END IF;

    INSERT INTO public.user_role_mapping (user_id, role_id, tenant_id, is_active, created_at, updated_at)
    VALUES (
        v_superadmin_user_id,
        v_superadmin_role_id,
        v_system_tenant_id,
        true,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    )
    ON CONFLICT (user_id, role_id, tenant_id) DO UPDATE
    SET is_active = true,
        updated_at = CURRENT_TIMESTAMP;
END $$;
