-- Migration: 042_superadmin_tenant_rls_bypass
-- Description: Updates RLS policy for tenants table to allow superadmins to see all tenants.
-- This allows superadmins to access the /superadmin/kb-usage page with full tenant data.

-- Update tenants select policy to allow superadmins to bypass
DROP POLICY IF EXISTS tenants_select_policy ON public.tenants;
CREATE POLICY tenants_select_policy
ON public.tenants
FOR SELECT
USING (
    public.is_superadmin()
    OR id = public.current_tenant_id_optional()
    OR EXISTS (
        SELECT 1
        FROM public.user_role_mapping AS urm
        JOIN public.users AS u ON u.id = urm.user_id
        WHERE urm.tenant_id = public.tenants.id
          AND urm.is_active = true
          AND u.email = public.current_user_email_optional()
    )
);

-- Also update user_role_mapping select policy for superadmin bypass
DROP POLICY IF EXISTS user_role_mapping_select_policy ON public.user_role_mapping;
CREATE POLICY user_role_mapping_select_policy
ON public.user_role_mapping
FOR SELECT
USING (
    public.is_superadmin()
    OR tenant_id = public.current_tenant_id_optional()
    OR (
        public.current_tenant_id_optional() IS NULL
        AND EXISTS (
            SELECT 1
            FROM public.users AS u
            WHERE u.id = public.user_role_mapping.user_id
              AND u.email = public.current_user_email_optional()
        )
    )
);
