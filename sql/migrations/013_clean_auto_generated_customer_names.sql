-- Remove auto-generated "User-{db_id}" customer_name from metadata
-- These were wrongly stored using session DB IDs instead of sequential ROW_NUMBER
-- The service layer now uses ROW_NUMBER-based user_display_id as the canonical name
UPDATE chat_sessions
SET metadata = metadata - 'customer_name'
WHERE metadata->>'customer_name' ~ '^User-\d+$';
