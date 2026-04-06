DO $$
DECLARE
    app_role_name text := 'knowledgebot_app';
    app_role_password text := 'PUT_YOUR_REAL_DECODED_PASSWORD_HERE';
    db_name text := current_database();
    grantor_role text := current_user;
    current_role_can_manage_roles boolean := false;
BEGIN
    SELECT r.rolsuper OR r.rolcreaterole
    INTO current_role_can_manage_roles
    FROM pg_roles r
    WHERE r.rolname = current_user;

    IF NOT COALESCE(current_role_can_manage_roles, false) THEN
        RAISE EXCEPTION
            'Current role "%" must have SUPERUSER or CREATEROLE to create/update "%".',
            current_user,
            app_role_name;
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
