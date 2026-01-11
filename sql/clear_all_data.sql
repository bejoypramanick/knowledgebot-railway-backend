-- WARNING: THIS SCRIPT WILL DELETE ALL DATA FROM ALL TABLES IN THE PUBLIC SCHEMA
-- USE WITH CAUTION

DO $$
DECLARE
    r RECORD;
BEGIN
    -- Iterate over all tables in the public schema
    FOR r IN (
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public' 
        -- Exclude migration tables if necessary (e.g., if using a migration tool that stores state in a table)
        -- AND tablename != 'schema_migrations' 
    ) LOOP
        RAISE NOTICE 'Truncating table: %', r.tablename;
        -- Truncate with CASCADE to handle foreign key references
        -- RESTART IDENTITY resets sequences
        EXECUTE 'TRUNCATE TABLE public.' || quote_ident(r.tablename) || ' RESTART IDENTITY CASCADE';
    END LOOP;
END $$;
