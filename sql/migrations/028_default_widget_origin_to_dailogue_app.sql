BEGIN;

ALTER TABLE public.widget_configuration
    ALTER COLUMN allowed_origins
    SET DEFAULT '["https://dailogue.globistaan.com"]'::jsonb;

UPDATE public.widget_configuration
SET allowed_origins = '["https://dailogue.globistaan.com"]'::jsonb
WHERE allowed_origins IS NULL
   OR allowed_origins = '[]'::jsonb;

COMMIT;
