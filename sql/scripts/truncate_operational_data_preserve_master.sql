-- Truncate operational/runtime data while preserving master/configuration data.
--
-- Intended use:
--   psql "$DATABASE_URL" -f sql/scripts/truncate_operational_data_preserve_master.sql
--
-- Preserved master/config tables:
--   tenants
--   users
--   roles
--   user_role_mapping
--   persona_configurations
--   security_settings
--   widget_configuration
--   widget_suggested_messages
--   notification_settings
--   llm_providers
--
-- Truncated examples:
--   chat_sessions, chat_messages, session_assignments, file_uploads,
--   scraped_websites, document_chunks, agent_run_steps,
--   token_usage_log, api_usage, notifications, admin_sessions,
--   admin_actions, service_health_checks, metrics, and any future public
--   table not listed in preserved_tables below.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '5min';

DO $$
DECLARE
    preserved_tables text[] := ARRAY[
        'tenants',
        'users',
        'roles',
        'user_role_mapping',
        'persona_configurations',
        'security_settings',
        'widget_configuration',
        'widget_suggested_messages',
        'notification_settings',
        'llm_providers'
    ];
    truncate_sql text;
    truncate_tables text[];
BEGIN
    SELECT array_agg(format('%I.%I', schemaname, tablename) ORDER BY tablename)
    INTO truncate_tables
    FROM pg_tables
    WHERE schemaname = 'public'
      AND tablename <> ALL (preserved_tables);

    IF truncate_tables IS NULL OR array_length(truncate_tables, 1) IS NULL THEN
        RAISE NOTICE 'No operational tables found to truncate.';
        RETURN;
    END IF;

    RAISE NOTICE 'Preserving master/config tables: %', array_to_string(preserved_tables, ', ');
    RAISE NOTICE 'Truncating operational tables: %', array_to_string(truncate_tables, ', ');

    truncate_sql := 'TRUNCATE TABLE '
        || array_to_string(truncate_tables, ', ')
        || ' RESTART IDENTITY CASCADE';

    EXECUTE truncate_sql;

    -- Keep provider/model configuration rows but reset runtime token counters.
    IF to_regclass('public.llm_providers') IS NOT NULL THEN
        UPDATE public.llm_providers
        SET token_used = 0,
            updated_at = CURRENT_TIMESTAMP;
        RAISE NOTICE 'Reset llm_providers.token_used to 0.';
    END IF;
END $$;

COMMIT;
