-- Migration 003: Create security_settings table
-- This table stores security configuration settings

CREATE TABLE IF NOT EXISTS public.security_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    setting_name varchar(100) NOT NULL,
    setting_value text NULL,
    setting_type varchar(50) DEFAULT 'string' NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp DEFAULT now() NULL,
    updated_at timestamp DEFAULT now() NULL,
    updated_by_email varchar(255) NULL,
    CONSTRAINT security_settings_pkey PRIMARY KEY (id),
    CONSTRAINT security_settings_name_unique UNIQUE (setting_name),
    CONSTRAINT valid_setting_type CHECK (setting_type IN ('string', 'integer', 'boolean', 'json'))
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_security_settings_active ON public.security_settings USING btree (is_active);
CREATE INDEX IF NOT EXISTS idx_security_settings_name ON public.security_settings USING btree (setting_name);

-- Add comments
COMMENT ON TABLE public.security_settings IS 'Security and configuration settings for the application';
COMMENT ON COLUMN public.security_settings.setting_name IS 'Name of the configuration setting';
COMMENT ON COLUMN public.security_settings.setting_value IS 'Value of the setting (stored as text, parsed as needed)';
COMMENT ON COLUMN public.security_settings.setting_type IS 'Data type: string, integer, boolean, or json';
COMMENT ON COLUMN public.security_settings.is_active IS 'Whether this setting is currently active';
COMMENT ON COLUMN public.security_settings.updated_by_email IS 'Email of the admin who last updated this setting';

-- Insert default security settings
INSERT INTO public.security_settings (setting_name, setting_value, setting_type, is_active, updated_by_email)
VALUES 
    ('max_file_size_mb', '10', 'integer', true, 'system@knowledgebot.com'),
    ('allowed_file_types', '["pdf", "docx", "txt", "md"]', 'json', true, 'system@knowledgebot.com'),
    ('session_timeout_minutes', '30', 'integer', true, 'system@knowledgebot.com'),
    ('enable_file_upload', 'true', 'boolean', true, 'system@knowledgebot.com'),
    ('max_chat_sessions_per_user', '5', 'integer', true, 'system@knowledgebot.com')
ON CONFLICT (setting_name) DO NOTHING;

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION public.update_security_settings_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language plpgsql;

CREATE TRIGGER security_settings_updated_at
    BEFORE UPDATE ON public.security_settings
    FOR EACH ROW
    EXECUTE FUNCTION public.update_security_settings_updated_at();
