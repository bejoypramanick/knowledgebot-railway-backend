-- Check actual column names in widget_configuration table
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'widget_configuration' 
ORDER BY column_name;
