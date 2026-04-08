-- Migration: 037_allow_superadmin_rls_bypass
-- Description: Updates RLS policies for widget_configuration to allow superadmins to bypass tenant checks.
-- This allows superadmins to seed default configurations for any tenant.

-- Update widget_configuration policies
DROP POLICY IF EXISTS widget_configuration_select_policy ON public.widget_configuration;
CREATE POLICY widget_configuration_select_policy ON public.widget_configuration
FOR SELECT USING (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin());

DROP POLICY IF EXISTS widget_configuration_insert_policy ON public.widget_configuration;
CREATE POLICY widget_configuration_insert_policy ON public.widget_configuration
FOR INSERT WITH CHECK (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin());

DROP POLICY IF EXISTS widget_configuration_update_policy ON public.widget_configuration;
CREATE POLICY widget_configuration_update_policy ON public.widget_configuration
FOR UPDATE USING (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin())
WITH CHECK (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin());

-- Update other core configuration tables to be consistent
DROP POLICY IF EXISTS persona_configurations_select_policy ON public.persona_configurations;
CREATE POLICY persona_configurations_select_policy ON public.persona_configurations
FOR SELECT USING (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin());

DROP POLICY IF EXISTS persona_configurations_insert_policy ON public.persona_configurations;
CREATE POLICY persona_configurations_insert_policy ON public.persona_configurations
FOR INSERT WITH CHECK (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin());

DROP POLICY IF EXISTS persona_configurations_update_policy ON public.persona_configurations;
CREATE POLICY persona_configurations_update_policy ON public.persona_configurations
FOR UPDATE USING (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin())
WITH CHECK (tenant_id = public.current_tenant_id_optional() OR public.is_superadmin());
