-- Migration: Add celery_task_id tracking for proper task cancellation
-- Purpose: Store Celery task IDs so we can revoke tasks from Redis when cancelled
-- Created: 2026-02-17

-- Add celery_task_id column to file_uploads table
ALTER TABLE public.file_uploads
ADD COLUMN IF NOT EXISTS celery_task_id varchar(255) NULL,
ADD COLUMN IF NOT EXISTS task_revoked_at timestamptz NULL;

-- Add index for faster lookups by task_id
CREATE INDEX IF NOT EXISTS idx_file_uploads_celery_task_id ON public.file_uploads(celery_task_id);

-- Comment explaining the column
COMMENT ON COLUMN public.file_uploads.celery_task_id IS 'Celery task ID - used to revoke tasks from Redis queue when cancelled';
COMMENT ON COLUMN public.file_uploads.task_revoked_at IS 'Timestamp when task was revoked from queue';

-- Add celery_task_id column to scraped_websites table
ALTER TABLE public.scraped_websites
ADD COLUMN IF NOT EXISTS celery_task_id varchar(255) NULL,
ADD COLUMN IF NOT EXISTS task_revoked_at timestamptz NULL;

-- Add index for faster lookups by task_id
CREATE INDEX IF NOT EXISTS idx_scraped_websites_celery_task_id ON public.scraped_websites(celery_task_id);

-- Comment explaining the columns
COMMENT ON COLUMN public.scraped_websites.celery_task_id IS 'Celery task ID - used to revoke tasks from Redis queue when cancelled';
COMMENT ON COLUMN public.scraped_websites.task_revoked_at IS 'Timestamp when task was revoked from queue';

-- Update the processing_status check constraint to include 'cancelled'
-- First drop the old constraint
ALTER TABLE public.file_uploads
DROP CONSTRAINT IF EXISTS valid_processing_status;

-- Add new constraint with 'cancelled' status
ALTER TABLE public.file_uploads
ADD CONSTRAINT valid_processing_status CHECK (processing_status::text = ANY (ARRAY[
    ('pending'::character varying)::text,
    ('processing'::character varying)::text,
    ('completed'::character varying)::text,
    ('failed'::character varying)::text,
    ('cancelled'::character varying)::text
]));

-- Do the same for scraped_websites
ALTER TABLE public.scraped_websites
DROP CONSTRAINT IF EXISTS valid_processing_status;

ALTER TABLE public.scraped_websites
ADD CONSTRAINT valid_processing_status CHECK (processing_status::text = ANY (ARRAY[
    ('pending'::character varying)::text,
    ('processing'::character varying)::text,
    ('completed'::character varying)::text,
    ('failed'::character varying)::text,
    ('cancelled'::character varying)::text
]));
