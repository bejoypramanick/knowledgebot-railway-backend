ALTER TABLE public.file_uploads ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;

ALTER TABLE public.scraped_websites ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;

UPDATE public.file_uploads SET completed_at = updated_at WHERE processing_status = 'completed' AND completed_at IS NULL;

UPDATE public.scraped_websites SET completed_at = updated_at WHERE processing_status = 'completed' AND parent_id IS NULL AND completed_at IS NULL;
