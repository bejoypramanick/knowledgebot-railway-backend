-- ============================================================================
-- PostgreSQL 18 Runtime Application Role for RLS-Safe Multi-Tenancy
-- ============================================================================
-- Purpose:
-- - Create or update a dedicated runtime role for the application services.
-- - Ensure the runtime role cannot bypass row-level security.
-- - Grant the runtime role the privileges needed by the app at runtime.
--
-- IMPORTANT:
-- - Run this as a privileged admin role (for example `postgres`).
-- - Replace the password placeholder below before executing.
-- - Use the DECODED current DB password here, not a URL-encoded password.
--
-- After this migration, update every runtime service DATABASE_URL to use:
--   knowledgebot_app:<same-password>
-- instead of:
--   postgres:<password>
-- ============================================================================

DO $$
DECLARE
    app_role_name text := 'knowledgebot_app';
    app_role_password text := 'REPLACE_WITH_DECODED_CURRENT_DB_PASSWORD';
    db_name text := current_database();
    grantor_role text := current_user;
BEGIN
    IF app_role_password = 'REPLACE_WITH_DECODED_CURRENT_DB_PASSWORD' THEN
        RAISE EXCEPTION
            'Replace the app_role_password placeholder in 025_create_runtime_app_role.sql before running it.';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname = app_role_name
    ) THEN
        EXECUTE format(
            'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
            app_role_name,
            app_role_password
        );
    ELSE
        EXECUTE format(
            'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
            app_role_name,
            app_role_password
        );
    END IF;

    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', db_name, app_role_name);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role_name);
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I',
        app_role_name
    );
    EXECUTE format(
        'GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I',
        app_role_name
    );
    EXECUTE format(
        'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO %I',
        app_role_name
    );

    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
         GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
        grantor_role,
        app_role_name
    );
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
         GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I',
        grantor_role,
        app_role_name
    );
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public
         GRANT EXECUTE ON FUNCTIONS TO %I',
        grantor_role,
        app_role_name
    );
END $$;

-- --------------------------------------------------------------------------
-- Verification
-- --------------------------------------------------------------------------
-- Run these after the migration:
--
-- SELECT rolname, rolsuper, rolbypassrls
-- FROM pg_roles
-- WHERE rolname IN ('postgres', 'knowledgebot_app');
--
-- Expected for knowledgebot_app:
--   rolsuper = false
--   rolbypassrls = false
--
-- Then update runtime DATABASE_URL values in Railway to use knowledgebot_app.
