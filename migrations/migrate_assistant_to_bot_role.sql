-- Migration to update existing chat_messages with 'assistant' role to 'bot' role
-- This fixes the constraint violation after changing the database insertion logic

-- Update all existing messages with role 'assistant' to 'bot'
UPDATE chat_messages
SET role = 'bot'
WHERE role = 'assistant';

-- Verify the update
SELECT
    role,
    COUNT(*) as message_count
FROM chat_messages
GROUP BY role
ORDER BY role;

COMMIT;