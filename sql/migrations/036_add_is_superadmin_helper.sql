-- Migration: 036_add_is_superadmin_helper
-- Description: Adds a helper function to check if the current user has the superadmin role.
-- Now uses a pre-verified session variable to avoid RLS recursion and visibility issues,
-- allowing us to maintain strict FORCE ROW LEVEL SECURITY.

-- Restore FORCE RLS (Defense in Depth)
ALTER TABLE public.user_role_mapping FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.is_superadmin()
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    -- Check the session variable populated by the API Gateway / Middleware
    SELECT COALESCE(current_setting('app.is_platform_admin', true), 'false') = 'true'
$$;

COMMENT ON FUNCTION public.is_superadmin() IS 'Returns true if the current session is verified as a platform superadmin.';


