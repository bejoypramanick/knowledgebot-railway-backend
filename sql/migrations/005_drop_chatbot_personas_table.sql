-- Migration: Drop unused chatbot_personas table
-- This table is no longer used since we're using persona_configurations table

-- Drop the unused chatbot_personas table if it exists
DROP TABLE IF EXISTS public.chatbot_personas;

COMMIT;
