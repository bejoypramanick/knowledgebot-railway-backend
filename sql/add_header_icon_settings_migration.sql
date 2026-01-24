-- Migration to add header icon settings to widget_configuration
-- Supports "Header Icon" feature

-- 1. Add header_icon columns to widget_configuration
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS header_icon_url TEXT;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS header_icon_zoom FLOAT DEFAULT 1.0;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS header_icon_position JSONB DEFAULT '{"x": 0, "y": 0}'::jsonb;
ALTER TABLE widget_configuration ADD COLUMN IF NOT EXISTS header_icon_filename VARCHAR(255);

-- 2. Log migration (optional, if audit log exists)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'configuration_audit_log') THEN
        INSERT INTO configuration_audit_log (action, details)
        VALUES ('migration', 'Added header icon columns to widget_configuration');
    END IF;
END $$;
