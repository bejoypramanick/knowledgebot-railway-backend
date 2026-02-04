-- DANGER: This script will DELETE ALL DATA and recreate the entire schema
-- Only run this if you want a completely fresh database

-- Step 1: Drop everything
DROP SCHEMA public CASCADE;

-- Step 2: Recreate schema
CREATE SCHEMA public AUTHORIZATION pg_database_owner;
COMMENT ON SCHEMA public IS '3NF Normalized Schema - All tables follow Third Normal Form';

-- Step 3: Grant permissions
GRANT ALL ON SCHEMA public TO postgres;
GRANT ALL ON SCHEMA public TO pg_database_owner;
GRANT ALL ON SCHEMA public TO PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO pg_database_owner;

-- Step 4: Create all sequences
CREATE SEQUENCE public.api_usage_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.api_usage_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.api_usage_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.api_usage_id_seq TO pg_database_owner;

CREATE SEQUENCE public.chat_feedback_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.chat_feedback_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_feedback_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_feedback_id_seq TO pg_database_owner;

CREATE SEQUENCE public.chat_messages_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.chat_messages_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_messages_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_messages_id_seq TO pg_database_owner;

CREATE SEQUENCE public.chat_sessions_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.chat_sessions_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.chat_sessions_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.chat_sessions_id_seq TO pg_database_owner;

CREATE SEQUENCE public.file_uploads_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.file_uploads_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.file_uploads_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.file_uploads_id_seq TO pg_database_owner;

CREATE SEQUENCE public.llm_providers_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.llm_providers_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.llm_providers_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.llm_providers_id_seq TO pg_database_owner;

CREATE SEQUENCE public.users_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.users_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.users_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.users_id_seq TO pg_database_owner;

CREATE SEQUENCE public.widget_configuration_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.widget_configuration_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_configuration_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_configuration_id_seq TO pg_database_owner;

CREATE SEQUENCE public.widget_scripts_id_seq
	INCREMENT BY 1
	MINVALUE 1
	MAXVALUE 9223372036854775807
	START 1
	CACHE 1
	NO CYCLE;

ALTER SEQUENCE public.widget_scripts_id_seq OWNER TO postgres;
GRANT ALL ON SEQUENCE public.widget_scripts_id_seq TO postgres;
GRANT ALL ON SEQUENCE public.widget_scripts_id_seq TO pg_database_owner;

-- Note: This is a partial recreation. 
-- For the complete schema, run the main database_schema.sql file after this.
-- Or use the two-step approach with reset_schema.sql + database_schema.sql
