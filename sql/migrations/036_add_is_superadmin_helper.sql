-- Migration: 036_add_is_superadmin_helper
-- Description: Adds a helper function to check if the current user has the superadmin role.
-- Also ensures the helper can read the mapping table by disabling FORCE RLS for the owner.

-- Disable FORCE RLS on membership table so the SECURITY DEFINER function can see all rows.
-- The table still has ENABLE RLS, so non-owner roles are still restricted.
ALTER TABLE public.user_role_mapping NO FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.is_superadmin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER -- Runs as the owner (postgres)
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.user_role_mapping AS urm
        JOIN public.users AS u ON u.id = urm.user_id
        JOIN public.roles AS r ON r.id = urm.role_id
        WHERE u.email = NULLIF(current_setting('app.current_user_email', true), '')
          AND r.role_name = 'superadmin'
          AND urm.is_active = true
    );
$$;

COMMENT ON FUNCTION public.is_superadmin() IS 'Returns true if the current session user email belongs to a superadmin. Bypasses RLS on user_role_mapping via SECURITY DEFINER.';

