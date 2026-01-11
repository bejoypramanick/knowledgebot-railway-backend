-- Check Admin Status
-- Run this to verify if your admin user exists and is confirmed.

SELECT '--- ADMINS TABLE ---' as table_name;
SELECT email, status, confirmed_at, created_at FROM admins;

SELECT '--- HUMAN AGENTS TABLE ---' as table_name;
SELECT email, role, status FROM human_agents;

SELECT '--- CHATBOT CONFIGURATION ---' as table_name;
SELECT admin_user, admin_emails FROM chatbot_configuration;
