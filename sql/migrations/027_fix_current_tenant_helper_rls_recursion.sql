-- ============================================================================
-- Fix recursive RLS evaluation in current_tenant_id_optional()
-- ============================================================================
-- Problem:
-- - current_tenant_id_optional() looked up tenants by slug from public.tenants.
-- - the tenants table RLS policy also calls current_tenant_id_optional().
-- - this creates recursive policy evaluation and can fail with:
--     stack depth limit exceeded
--
-- Fix:
-- - only read the tenant UUID from the per-request PostgreSQL session setting.
-- - tenant slug remains available separately through current_tenant_slug_optional().
-- - application code already sets tenant_id directly on trusted authenticated and
--   widget requests, so this keeps tenant isolation intact without recursion.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.current_tenant_id_optional()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
$$;
