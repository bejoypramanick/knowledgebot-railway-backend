-- Add default suggested messages to widget_suggested_messages table
-- This script adds common suggested messages that users can click to start conversations

INSERT INTO widget_suggested_messages (widget_config_id, message_text, display_order, is_active, created_at, updated_at)
VALUES 
  (1, 'What can you help me with?', 0, true, NOW(), NOW()),
  (1, 'Tell me about your services', 1, true, NOW(), NOW()),
  (1, 'How do I get started?', 2, true, NOW(), NOW()),
  (1, 'I need assistance', 3, true, NOW(), NOW())
ON CONFLICT DO NOTHING;
