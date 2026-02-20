-- Add celery_task_id column to scraped_websites table for task tracking
-- Created: 2026-02-17
-- Purpose: Store Celery task IDs for cancellation and tracking

ALTER TABLE scraped_websites 
ADD COLUMN celery_task_id VARCHAR(255);

-- Create index for faster task lookups
CREATE INDEX IF NOT EXISTS idx_scraped_websites_celery_task_id 
ON scraped_websites(celery_task_id);