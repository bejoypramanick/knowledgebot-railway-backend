-- ============================================================================
-- PostgreSQL 18 Multi-Tenant Isolation
-- ============================================================================
-- Introduces tenant-aware role memberships and tenant isolation across
-- configuration, chat, knowledge base, worker, and audit tables.
--
-- Backward compatibility:
-- - Existing rows are backfilled into a deterministic default tenant.
-- - Public/anonymous widget traffic can continue to use the default tenant
--   when the caller does not yet provide an explicit tenant.
-- ============================================================================

SET statement_timeout = '300s';
SET lock_timeout = '30s';

-- --------------------------------------------------------------------------
-- Tenant primitives
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.tenants (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    slug varchar(100) NOT NULL UNIQUE,
    name varchar(255) NOT NULL,
    description text NULL,
    is_active bool NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE OR REPLACE TRIGGER tenants_updated_at_trigger
BEFORE UPDATE ON public.tenants
FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();

CREATE OR REPLACE FUNCTION public.default_tenant_id()
RETURNS uuid
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT '00000000-0000-7000-8000-000000000001'::uuid
$$;

CREATE OR REPLACE FUNCTION public.current_tenant_id_optional()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION public.current_tenant_slug_optional()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_tenant_slug', true), '')
$$;

CREATE OR REPLACE FUNCTION public.current_user_email_optional()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_user_email', true), '')
$$;

INSERT INTO public.tenants (id, slug, name, description, is_active, metadata)
VALUES (
    public.default_tenant_id(),
    'default',
    'Default Tenant',
    'Compatibility tenant containing pre-multitenant data.',
    true,
    '{"seeded_by":"024_multitenant_isolation"}'::jsonb
)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug,
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    is_active = true,
    metadata = public.tenants.metadata || EXCLUDED.metadata,
    updated_at = CURRENT_TIMESTAMP;

-- --------------------------------------------------------------------------
-- Core membership model
-- --------------------------------------------------------------------------

ALTER TABLE public.user_role_mapping
    ADD COLUMN IF NOT EXISTS tenant_id uuid;

UPDATE public.user_role_mapping
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

ALTER TABLE public.user_role_mapping
    ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();

ALTER TABLE public.user_role_mapping
    ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE public.user_role_mapping
    DROP CONSTRAINT IF EXISTS user_role_mapping_user_role_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_role_mapping_user_role_tenant
    ON public.user_role_mapping (user_id, role_id, tenant_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_role_mapping_tenant_user_role
    ON public.user_role_mapping (tenant_id, user_role_id);

CREATE INDEX IF NOT EXISTS idx_user_role_mapping_tenant_role_user
    ON public.user_role_mapping (tenant_id, role_id, user_id)
    INCLUDE (is_active, created_at);

DO $$
BEGIN
    BEGIN
        ALTER TABLE public.user_role_mapping
            ADD CONSTRAINT user_role_mapping_tenant_id_fkey
            FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END $$;

-- --------------------------------------------------------------------------
-- Tenant columns and backfill
-- --------------------------------------------------------------------------

ALTER TABLE public.admin_sessions ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.admin_actions ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.api_usage ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.notification_settings ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.notifications ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.persona_configurations ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.widget_configuration ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.widget_suggested_messages ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.chat_messages ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.file_uploads ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.scraped_websites ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.session_assignments ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.tables_metadata ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.agent_run_steps ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.token_usage_log ADD COLUMN IF NOT EXISTS tenant_id uuid;
ALTER TABLE public.document_chunks ADD COLUMN IF NOT EXISTS tenant_id uuid;

UPDATE public.admin_sessions AS s
SET tenant_id = COALESCE(urm.tenant_id, public.default_tenant_id())
FROM public.user_role_mapping AS urm
WHERE s.tenant_id IS NULL
  AND s.user_role_id = urm.user_role_id;

UPDATE public.admin_sessions
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.admin_actions AS a
SET tenant_id = COALESCE(s.tenant_id, public.default_tenant_id())
FROM public.admin_sessions AS s
WHERE a.tenant_id IS NULL
  AND a.session_id = s.id;

UPDATE public.admin_actions
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.api_usage
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.notification_settings
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.notifications
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.persona_configurations
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.widget_configuration
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.widget_suggested_messages AS wsm
SET tenant_id = COALESCE(wc.tenant_id, public.default_tenant_id())
FROM public.widget_configuration AS wc
WHERE wsm.tenant_id IS NULL
  AND wsm.widget_config_id = wc.id;

UPDATE public.widget_suggested_messages
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.chat_sessions AS cs
SET tenant_id = COALESCE(urm.tenant_id, public.default_tenant_id())
FROM public.user_role_mapping AS urm
WHERE cs.tenant_id IS NULL
  AND cs.user_role_id = urm.user_role_id;

UPDATE public.chat_sessions
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.chat_messages AS cm
SET tenant_id = COALESCE(cs.tenant_id, public.default_tenant_id())
FROM public.chat_sessions AS cs
WHERE cm.tenant_id IS NULL
  AND cm.session_id = cs.id;

UPDATE public.chat_messages
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.file_uploads AS fu
SET tenant_id = COALESCE(urm.tenant_id, public.default_tenant_id())
FROM public.user_role_mapping AS urm
WHERE fu.tenant_id IS NULL
  AND fu.user_role_id = urm.user_role_id;

UPDATE public.file_uploads
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.scraped_websites AS sw
SET tenant_id = COALESCE(urm.tenant_id, public.default_tenant_id())
FROM public.user_role_mapping AS urm
WHERE sw.tenant_id IS NULL
  AND sw.user_role_id = urm.user_role_id;

UPDATE public.scraped_websites
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.session_assignments AS sa
SET tenant_id = COALESCE(cs.tenant_id, public.default_tenant_id())
FROM public.chat_sessions AS cs
WHERE sa.tenant_id IS NULL
  AND sa.session_id = cs.id;

UPDATE public.session_assignments
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.tables_metadata AS tm
SET tenant_id = COALESCE(fu.tenant_id, public.default_tenant_id())
FROM public.file_uploads AS fu
WHERE tm.tenant_id IS NULL
  AND tm.file_upload_id = fu.id;

UPDATE public.tables_metadata AS tm
SET tenant_id = COALESCE(sw.tenant_id, public.default_tenant_id())
FROM public.scraped_websites AS sw
WHERE tm.tenant_id IS NULL
  AND tm.scraped_website_id = sw.id;

UPDATE public.tables_metadata
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.agent_run_steps AS ars
SET tenant_id = COALESCE(cs.tenant_id, public.default_tenant_id())
FROM public.chat_sessions AS cs
WHERE ars.tenant_id IS NULL
  AND ars.session_id = cs.id;

UPDATE public.agent_run_steps
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.token_usage_log AS tul
SET tenant_id = COALESCE(cs.tenant_id, public.default_tenant_id())
FROM public.chat_sessions AS cs
WHERE tul.tenant_id IS NULL
  AND tul.session_id = cs.id;

UPDATE public.token_usage_log AS tul
SET tenant_id = COALESCE(cm.tenant_id, public.default_tenant_id())
FROM public.chat_messages AS cm
WHERE tul.tenant_id IS NULL
  AND tul.message_id = cm.id;

UPDATE public.token_usage_log
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

UPDATE public.document_chunks AS dc
SET tenant_id = COALESCE(fu.tenant_id, public.default_tenant_id())
FROM public.file_uploads AS fu
WHERE dc.tenant_id IS NULL
  AND dc.document_type = 'file'
  AND dc.document_id = fu.id;

UPDATE public.document_chunks AS dc
SET tenant_id = COALESCE(sw.tenant_id, public.default_tenant_id())
FROM public.scraped_websites AS sw
WHERE dc.tenant_id IS NULL
  AND dc.document_type = 'website'
  AND dc.document_id = sw.id;

UPDATE public.document_chunks
SET tenant_id = public.default_tenant_id()
WHERE tenant_id IS NULL;

ALTER TABLE public.admin_sessions ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.admin_actions ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.api_usage ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.notification_settings ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.notifications ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.persona_configurations ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.widget_configuration ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.widget_suggested_messages ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.chat_sessions ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.chat_messages ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.file_uploads ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.scraped_websites ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.session_assignments ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.tables_metadata ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.agent_run_steps ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.token_usage_log ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();
ALTER TABLE public.document_chunks ALTER COLUMN tenant_id SET DEFAULT public.current_tenant_id_optional();

ALTER TABLE public.admin_sessions ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.admin_actions ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.api_usage ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.notification_settings ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.notifications ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.persona_configurations ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.widget_configuration ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.widget_suggested_messages ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.chat_sessions ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.chat_messages ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.file_uploads ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.scraped_websites ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.session_assignments ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.tables_metadata ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.agent_run_steps ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.token_usage_log ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE public.document_chunks ALTER COLUMN tenant_id SET NOT NULL;

-- --------------------------------------------------------------------------
-- Tenant-scoped uniqueness and supporting indexes
-- --------------------------------------------------------------------------

ALTER TABLE public.widget_configuration
    DROP CONSTRAINT IF EXISTS widget_config_singleton;

CREATE UNIQUE INDEX IF NOT EXISTS idx_widget_configuration_tenant_singleton
    ON public.widget_configuration (tenant_id, is_singleton)
    WHERE is_singleton = true;

CREATE UNIQUE INDEX IF NOT EXISTS idx_widget_configuration_tenant_id
    ON public.widget_configuration (tenant_id, id);

ALTER TABLE public.persona_configurations
    DROP CONSTRAINT IF EXISTS persona_configurations_persona_name_key;

CREATE UNIQUE INDEX IF NOT EXISTS idx_persona_configurations_tenant_name
    ON public.persona_configurations (tenant_id, persona_name);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_tenant_id
    ON public.chat_sessions (tenant_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_tenant_id
    ON public.chat_messages (tenant_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_admin_sessions_tenant_id
    ON public.admin_sessions (tenant_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_file_uploads_tenant_id
    ON public.file_uploads (tenant_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_scraped_websites_tenant_id
    ON public.scraped_websites (tenant_id, id);

CREATE INDEX IF NOT EXISTS idx_notifications_tenant_email_created
    ON public.notifications (tenant_id, user_email, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_activity
    ON public.chat_sessions (tenant_id, last_activity_at DESC);

CREATE INDEX IF NOT EXISTS idx_file_uploads_tenant_status_created
    ON public.file_uploads (tenant_id, processing_status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_scraped_websites_tenant_status_created
    ON public.scraped_websites (tenant_id, processing_status, created_at DESC);

DO $$
DECLARE
    tenant_table text;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY[
        'admin_sessions',
        'admin_actions',
        'api_usage',
        'notification_settings',
        'notifications',
        'persona_configurations',
        'widget_configuration',
        'widget_suggested_messages',
        'chat_sessions',
        'chat_messages',
        'file_uploads',
        'scraped_websites',
        'session_assignments',
        'tables_metadata',
        'agent_run_steps',
        'token_usage_log',
        'document_chunks'
    ]
    LOOP
        BEGIN
            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY (tenant_id) REFERENCES public.tenants(id) ON DELETE CASCADE',
                tenant_table,
                tenant_table || '_tenant_id_fkey'
            );
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END;
    END LOOP;
END $$;

DO $$
BEGIN
    BEGIN
        ALTER TABLE public.admin_sessions
            ADD CONSTRAINT admin_sessions_tenant_user_role_fkey
            FOREIGN KEY (tenant_id, user_role_id)
            REFERENCES public.user_role_mapping(tenant_id, user_role_id)
            ON DELETE RESTRICT;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;

    BEGIN
        ALTER TABLE public.chat_sessions
            ADD CONSTRAINT chat_sessions_tenant_user_role_fkey
            FOREIGN KEY (tenant_id, user_role_id)
            REFERENCES public.user_role_mapping(tenant_id, user_role_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;

    BEGIN
        ALTER TABLE public.file_uploads
            ADD CONSTRAINT file_uploads_tenant_user_role_fkey
            FOREIGN KEY (tenant_id, user_role_id)
            REFERENCES public.user_role_mapping(tenant_id, user_role_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;

    BEGIN
        ALTER TABLE public.scraped_websites
            ADD CONSTRAINT scraped_websites_tenant_user_role_fkey
            FOREIGN KEY (tenant_id, user_role_id)
            REFERENCES public.user_role_mapping(tenant_id, user_role_id)
            ON DELETE SET NULL;
    EXCEPTION WHEN duplicate_object THEN
        NULL;
    END;
END $$;

-- --------------------------------------------------------------------------
-- Tenant consistency triggers
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.sync_chat_session_child_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    resolved_tenant_id uuid;
BEGIN
    SELECT tenant_id INTO resolved_tenant_id
    FROM public.chat_sessions
    WHERE id = NEW.session_id;

    IF resolved_tenant_id IS NULL THEN
        RAISE EXCEPTION 'Cannot resolve tenant for chat session %', NEW.session_id;
    END IF;

    NEW.tenant_id := resolved_tenant_id;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_admin_session_child_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    resolved_tenant_id uuid;
BEGIN
    SELECT tenant_id INTO resolved_tenant_id
    FROM public.admin_sessions
    WHERE id = NEW.session_id;

    IF resolved_tenant_id IS NULL THEN
        RAISE EXCEPTION 'Cannot resolve tenant for admin session %', NEW.session_id;
    END IF;

    NEW.tenant_id := resolved_tenant_id;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_widget_child_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    resolved_tenant_id uuid;
BEGIN
    SELECT tenant_id INTO resolved_tenant_id
    FROM public.widget_configuration
    WHERE id = NEW.widget_config_id;

    IF resolved_tenant_id IS NULL THEN
        RAISE EXCEPTION 'Cannot resolve tenant for widget configuration %', NEW.widget_config_id;
    END IF;

    NEW.tenant_id := resolved_tenant_id;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_table_metadata_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    resolved_tenant_id uuid;
BEGIN
    IF NEW.file_upload_id IS NOT NULL THEN
        SELECT tenant_id INTO resolved_tenant_id
        FROM public.file_uploads
        WHERE id = NEW.file_upload_id;
    ELSIF NEW.scraped_website_id IS NOT NULL THEN
        SELECT tenant_id INTO resolved_tenant_id
        FROM public.scraped_websites
        WHERE id = NEW.scraped_website_id;
    END IF;

    IF resolved_tenant_id IS NULL THEN
        RAISE EXCEPTION 'Cannot resolve tenant for tables_metadata row';
    END IF;

    NEW.tenant_id := resolved_tenant_id;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_token_usage_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    resolved_tenant_id uuid;
BEGIN
    IF NEW.session_id IS NOT NULL THEN
        SELECT tenant_id INTO resolved_tenant_id
        FROM public.chat_sessions
        WHERE id = NEW.session_id;
    END IF;

    IF resolved_tenant_id IS NULL AND NEW.message_id IS NOT NULL THEN
        SELECT tenant_id INTO resolved_tenant_id
        FROM public.chat_messages
        WHERE id = NEW.message_id;
    END IF;

    IF resolved_tenant_id IS NULL THEN
        resolved_tenant_id := public.current_tenant_id_optional();
    END IF;

    IF resolved_tenant_id IS NULL THEN
        RAISE EXCEPTION 'Cannot resolve tenant for token usage row';
    END IF;

    NEW.tenant_id := resolved_tenant_id;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.sync_document_chunk_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    resolved_tenant_id uuid;
BEGIN
    IF NEW.document_type = 'file' THEN
        SELECT tenant_id INTO resolved_tenant_id
        FROM public.file_uploads
        WHERE id = NEW.document_id;
    ELSIF NEW.document_type = 'website' THEN
        SELECT tenant_id INTO resolved_tenant_id
        FROM public.scraped_websites
        WHERE id = NEW.document_id;
    END IF;

    IF resolved_tenant_id IS NULL THEN
        RAISE EXCEPTION 'Cannot resolve tenant for document chunk %/%', NEW.document_type, NEW.document_id;
    END IF;

    NEW.tenant_id := resolved_tenant_id;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS widget_suggested_messages_tenant_sync_trigger ON public.widget_suggested_messages;
CREATE TRIGGER widget_suggested_messages_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.widget_suggested_messages
FOR EACH ROW EXECUTE FUNCTION public.sync_widget_child_tenant();

DROP TRIGGER IF EXISTS chat_messages_tenant_sync_trigger ON public.chat_messages;
CREATE TRIGGER chat_messages_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.chat_messages
FOR EACH ROW EXECUTE FUNCTION public.sync_chat_session_child_tenant();

DROP TRIGGER IF EXISTS session_assignments_tenant_sync_trigger ON public.session_assignments;
CREATE TRIGGER session_assignments_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.session_assignments
FOR EACH ROW EXECUTE FUNCTION public.sync_chat_session_child_tenant();

DROP TRIGGER IF EXISTS agent_run_steps_tenant_sync_trigger ON public.agent_run_steps;
CREATE TRIGGER agent_run_steps_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.agent_run_steps
FOR EACH ROW EXECUTE FUNCTION public.sync_chat_session_child_tenant();

DROP TRIGGER IF EXISTS admin_actions_tenant_sync_trigger ON public.admin_actions;
CREATE TRIGGER admin_actions_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.admin_actions
FOR EACH ROW EXECUTE FUNCTION public.sync_admin_session_child_tenant();

DROP TRIGGER IF EXISTS tables_metadata_tenant_sync_trigger ON public.tables_metadata;
CREATE TRIGGER tables_metadata_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.tables_metadata
FOR EACH ROW EXECUTE FUNCTION public.sync_table_metadata_tenant();

DROP TRIGGER IF EXISTS token_usage_log_tenant_sync_trigger ON public.token_usage_log;
CREATE TRIGGER token_usage_log_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.token_usage_log
FOR EACH ROW EXECUTE FUNCTION public.sync_token_usage_tenant();

DROP TRIGGER IF EXISTS document_chunks_tenant_sync_trigger ON public.document_chunks;
CREATE TRIGGER document_chunks_tenant_sync_trigger
BEFORE INSERT OR UPDATE ON public.document_chunks
FOR EACH ROW EXECUTE FUNCTION public.sync_document_chunk_tenant();

-- --------------------------------------------------------------------------
-- Tenant bootstrap defaults
-- --------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.bootstrap_tenant_defaults()
RETURNS trigger
LANGUAGE plpgsql
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
    ON CONFLICT DO NOTHING;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS tenants_bootstrap_defaults_trigger ON public.tenants;
CREATE TRIGGER tenants_bootstrap_defaults_trigger
AFTER INSERT ON public.tenants
FOR EACH ROW EXECUTE FUNCTION public.bootstrap_tenant_defaults();

-- --------------------------------------------------------------------------
-- Row-level tenant isolation
-- --------------------------------------------------------------------------

ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenants FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenants_select_policy ON public.tenants;
CREATE POLICY tenants_select_policy
ON public.tenants
FOR SELECT
USING (
    id = public.current_tenant_id_optional()
    OR EXISTS (
        SELECT 1
        FROM public.user_role_mapping AS urm
        JOIN public.users AS u ON u.id = urm.user_id
        WHERE urm.tenant_id = public.tenants.id
          AND urm.is_active = true
          AND u.email = public.current_user_email_optional()
    )
);

DROP POLICY IF EXISTS tenants_write_policy ON public.tenants;
CREATE POLICY tenants_write_policy
ON public.tenants
FOR ALL
USING (id = public.current_tenant_id_optional())
WITH CHECK (id = COALESCE(public.current_tenant_id_optional(), id));

ALTER TABLE public.user_role_mapping ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_role_mapping FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_role_mapping_select_policy ON public.user_role_mapping;
CREATE POLICY user_role_mapping_select_policy
ON public.user_role_mapping
FOR SELECT
USING (
    tenant_id = public.current_tenant_id_optional()
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

DROP POLICY IF EXISTS user_role_mapping_write_policy ON public.user_role_mapping;
CREATE POLICY user_role_mapping_write_policy
ON public.user_role_mapping
FOR ALL
USING (tenant_id = public.current_tenant_id_optional())
WITH CHECK (tenant_id = public.current_tenant_id_optional());

DO $$
DECLARE
    tenant_table text;
BEGIN
    FOREACH tenant_table IN ARRAY ARRAY[
        'admin_sessions',
        'admin_actions',
        'api_usage',
        'notification_settings',
        'notifications',
        'persona_configurations',
        'widget_configuration',
        'widget_suggested_messages',
        'chat_sessions',
        'chat_messages',
        'file_uploads',
        'scraped_websites',
        'session_assignments',
        'tables_metadata',
        'agent_run_steps',
        'token_usage_log',
        'document_chunks'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tenant_table);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tenant_table);

        EXECUTE format('DROP POLICY IF EXISTS %I_select_policy ON public.%I', tenant_table, tenant_table);
        EXECUTE format(
            'CREATE POLICY %I_select_policy ON public.%I FOR SELECT USING (tenant_id = public.current_tenant_id_optional())',
            tenant_table,
            tenant_table
        );

        EXECUTE format('DROP POLICY IF EXISTS %I_insert_policy ON public.%I', tenant_table, tenant_table);
        EXECUTE format(
            'CREATE POLICY %I_insert_policy ON public.%I FOR INSERT WITH CHECK (tenant_id = public.current_tenant_id_optional())',
            tenant_table,
            tenant_table
        );

        EXECUTE format('DROP POLICY IF EXISTS %I_update_policy ON public.%I', tenant_table, tenant_table);
        EXECUTE format(
            'CREATE POLICY %I_update_policy ON public.%I FOR UPDATE USING (tenant_id = public.current_tenant_id_optional()) WITH CHECK (tenant_id = public.current_tenant_id_optional())',
            tenant_table,
            tenant_table
        );

        EXECUTE format('DROP POLICY IF EXISTS %I_delete_policy ON public.%I', tenant_table, tenant_table);
        EXECUTE format(
            'CREATE POLICY %I_delete_policy ON public.%I FOR DELETE USING (tenant_id = public.current_tenant_id_optional())',
            tenant_table,
            tenant_table
        );
    END LOOP;
END $$;
