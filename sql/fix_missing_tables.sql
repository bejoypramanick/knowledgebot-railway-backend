-- Fix missing tables that are causing "relation does not exist" errors
-- Run this script to create the missing user_role_mapping related tables

-- Create roles table if it doesn't exist
CREATE TABLE IF NOT EXISTS public.roles (
    id serial4 NOT NULL,
    role_name varchar(50) NOT NULL,
    role_description text NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT roles_pkey PRIMARY KEY (id),
    CONSTRAINT roles_role_name_key UNIQUE (role_name)
);

CREATE INDEX IF NOT EXISTS idx_roles_role_name ON public.roles USING btree (role_name);
COMMENT ON TABLE public.roles IS 'User roles definition';

-- Create users table if it doesn't exist
CREATE TABLE IF NOT EXISTS public.users (
    id serial4 NOT NULL,
    email varchar(255) NOT NULL,
    display_name varchar(255) NULL,
    email_verified bool DEFAULT false NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT users_pkey PRIMARY KEY (id),
    CONSTRAINT users_email_key UNIQUE (email)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users USING btree (email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON public.users USING btree (created_at DESC);
COMMENT ON TABLE public.users IS 'User accounts from Firebase Auth';

-- Create user_role_mapping table if it doesn't exist
CREATE TABLE IF NOT EXISTS public.user_role_mapping (
    user_role_id serial4 NOT NULL,
    user_id int4 NOT NULL,
    role_id int4 NOT NULL,
    created_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    updated_at timestamptz DEFAULT CURRENT_TIMESTAMP NULL,
    CONSTRAINT user_role_mapping_pkey PRIMARY KEY (user_role_id),
    CONSTRAINT user_role_mapping_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE,
    CONSTRAINT user_role_mapping_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE,
    CONSTRAINT user_role_mapping_user_role_key UNIQUE (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_user_role_mapping_user_id ON public.user_role_mapping USING btree (user_id);
CREATE INDEX IF NOT EXISTS idx_user_role_mapping_role_id ON public.user_role_mapping USING btree (role_id);
COMMENT ON TABLE public.user_role_mapping IS 'Mapping between users and their roles';

-- Insert default roles if they don't exist
INSERT INTO public.roles (role_name, role_description) VALUES 
    ('admin', 'System administrator with full access'),
    ('human_agent', 'Human agent for customer support'),
    ('user', 'Regular user with basic access')
ON CONFLICT (role_name) DO NOTHING;

-- Grant permissions
ALTER TABLE public.roles OWNER TO postgres;
GRANT ALL ON TABLE public.roles TO postgres;
GRANT ALL ON TABLE public.roles TO pg_database_owner;

ALTER TABLE public.users OWNER TO postgres;
GRANT ALL ON TABLE public.users TO postgres;
GRANT ALL ON TABLE public.users TO pg_database_owner;

ALTER TABLE public.user_role_mapping OWNER TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO postgres;
GRANT ALL ON TABLE public.user_role_mapping TO pg_database_owner;

-- Verification query
SELECT 
    'users' as table_name, 
    EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'users') as exists
UNION ALL
SELECT 
    'roles' as table_name, 
    EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'roles') as exists
UNION ALL
SELECT 
    'user_role_mapping' as table_name, 
    EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'user_role_mapping') as exists;
