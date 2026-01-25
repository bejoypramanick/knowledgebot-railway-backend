-- Migration to remove header icon columns from widget_configuration
-- Reverses the header icon feature

-- 1. Drop header icon columns from widget_configuration
ALTER TABLE widget_configuration DROP COLUMN IF EXISTS header_icon_url;
ALTER TABLE widget_configuration DROP COLUMN IF EXISTS header_icon_zoom;
ALTER TABLE widget_configuration DROP COLUMN IF EXISTS header_icon_position;
ALTER TABLE widget_configuration DROP COLUMN IF EXISTS header_icon_filename;

-- 2. Log migration (optional, if audit log exists)
DO $$
BEGIN
    IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'configuration_audit_log') THEN
        INSERT INTO configuration_audit_log (action, details)
        VALUES ('migration', 'Removed header icon columns from widget_configuration');
    END IF;
END $$;

-- 3. Verify columns were removed
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'widget_configuration' 
AND column_name LIKE 'header_icon%';
