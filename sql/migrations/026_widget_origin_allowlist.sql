BEGIN;

ALTER TABLE public.widget_configuration
    ADD COLUMN IF NOT EXISTS allowed_origins jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.widget_configuration
    DROP CONSTRAINT IF EXISTS widget_configuration_allowed_origins_is_array;

ALTER TABLE public.widget_configuration
    ADD CONSTRAINT widget_configuration_allowed_origins_is_array
    CHECK (jsonb_typeof(allowed_origins) = 'array');

UPDATE public.widget_configuration
SET allowed_origins = '[]'::jsonb
WHERE allowed_origins IS NULL;

COMMIT;
