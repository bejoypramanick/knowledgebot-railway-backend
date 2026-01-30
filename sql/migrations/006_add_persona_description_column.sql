-- Migration: Add persona_description column to persona_configurations table
-- This migration adds the missing persona_description column

-- Add persona_description column if it doesn't exist
DO $$
BEGIN
    -- Check if column exists
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'persona_configurations' 
        AND column_name = 'persona_description'
    ) THEN
        ALTER TABLE persona_configurations 
        ADD COLUMN persona_description TEXT;
        
        RAISE NOTICE 'persona_description column added to persona_configurations table';
    ELSE
        RAISE NOTICE 'persona_description column already exists in persona_configurations table';
    END IF;
END $$;

-- Update existing records to have default descriptions if persona_description is NULL
UPDATE persona_configurations 
SET persona_description = CASE 
    WHEN persona_name = 'KnowledgeBot' THEN 'A helpful AI assistant for knowledge management'
    WHEN persona_name = 'Friendly Receptionist' THEN 'A warm and professional receptionist persona'
    WHEN persona_name = 'Upselling Assistant' THEN 'A strategic upselling assistant persona'
    WHEN persona_name = 'Fast Paced Problem Solver' THEN 'A quick and efficient problem solver persona'
    WHEN persona_name = 'Knowledge Based Expert' THEN 'A documentation-based expert persona'
    WHEN persona_name = 'The Agile Troubleshooter' THEN 'An agile diagnostic problem solver persona'
    WHEN persona_name = 'The Welcoming Guide' THEN 'A patient onboarding specialist persona'
    ELSE 'AI assistant persona'
END
WHERE persona_description IS NULL;

-- Verify the column was added and data updated
SELECT 
    persona_name, 
    persona_description, 
    is_active, 
    created_at, 
    updated_at 
FROM persona_configurations 
ORDER BY persona_name;
