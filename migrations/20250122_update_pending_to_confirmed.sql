-- Migration: Update all pending admin and human agent records to confirmed status
-- This migration is needed after removing email confirmation dependency
-- Run this migration to ensure existing pending users become active immediately

-- Update all pending admins to confirmed
UPDATE admins
SET status = 'confirmed', confirmed_at = NOW()
WHERE status = 'pending';

-- Update all pending human agents to confirmed
UPDATE human_agents
SET status = 'confirmed', confirmed_at = NOW()
WHERE status = 'pending';

-- Log the changes
SELECT
    'Admins updated: ' || COUNT(*) as admin_updates
FROM admins
WHERE status = 'confirmed' AND confirmed_at IS NOT NULL;

SELECT
    'Human agents updated: ' || COUNT(*) as agent_updates
FROM human_agents
WHERE status = 'confirmed' AND confirmed_at IS NOT NULL;