-- DANGER: This script will DELETE ALL DATA in the public schema
-- Run this only if you want to completely reset the database

-- Drop the entire public schema and recreate it
DROP SCHEMA public CASCADE;

-- Recreate the public schema
CREATE SCHEMA public AUTHORIZATION pg_database_owner;

COMMENT ON SCHEMA public IS '3NF Normalized Schema - All tables follow Third Normal Form';

-- Grant permissions
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT ALL ON SCHEMA public TO PUBLIC;

-- Set default permissions for new objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO pg_database_owner;

-- Now you can run the main database_schema.sql file
-- Run this after this script completes:
-- psql $DATABASE_URL -f sql/database_schema.sql
