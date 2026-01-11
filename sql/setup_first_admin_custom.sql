-- ============================================================================
-- SETUP FIRST ADMIN USER (CUSTOMIZABLE VERSION)
-- Edit the variables below to customize the first admin user
-- Run this after populating email_oauth_credentials table
-- ============================================================================

-- ===== CUSTOMIZE THESE VALUES =====
-- Change these values according to your needs
DO $$
DECLARE
    -- Admin details - CHANGE THESE VALUES
    admin_email VARCHAR(255) := 'your-admin@example.com';  -- Change to your desired admin email
    admin_password VARCHAR(255) := 'YourSecurePassword123!';  -- Change to your desired password
    display_id VARCHAR(100) := 'ADM-000001';  -- Change to your desired display ID
BEGIN

    -- Insert the first admin user
    INSERT INTO admins (
        email,
        status,
        auto_generated_password,
        confirmed_at,
        created_by_email
    )
    VALUES (
        admin_email,
        'confirmed',
        admin_password,
        CURRENT_TIMESTAMP,
        NULL  -- First admin has no creator
    )
    ON CONFLICT (email) DO UPDATE SET
        status = 'confirmed',
        auto_generated_password = EXCLUDED.auto_generated_password,
        confirmed_at = CURRENT_TIMESTAMP;

    -- Create user_unique_id for display purposes
    INSERT INTO user_unique_ids (
        email,
        unique_id,
        role,
        created_at
    )
    VALUES (
        admin_email,
        display_id,
        'admin',
        CURRENT_TIMESTAMP
    )
    ON CONFLICT (email, role) DO UPDATE SET
        unique_id = EXCLUDED.unique_id;

    -- Log the creation
    RAISE NOTICE '================================================';
    RAISE NOTICE 'FIRST ADMIN USER CREATED';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Email: %', admin_email;
    RAISE NOTICE 'Password: %', admin_password;
    RAISE NOTICE 'Display ID: %', display_id;
    RAISE NOTICE 'Status: confirmed';
    RAISE NOTICE '================================================';

END $$;

-- ============================================================================
-- VERIFY ADMIN CREATION
-- ============================================================================

-- Check that the admin was created
SELECT
    a.id,
    a.email,
    a.status,
    a.confirmed_at,
    a.created_at,
    u.unique_id as display_id
FROM admins a
LEFT JOIN user_unique_ids u ON a.email = u.email AND u.role = 'admin'
WHERE a.email = 'your-admin@example.com';  -- Change this to match your email

-- ============================================================================
-- USAGE INSTRUCTIONS
-- ============================================================================

/*
TO USE THIS SCRIPT:

1. Edit the DECLARE block above:
   - Change admin_email to your desired admin email
   - Change admin_password to your desired password
   - Change display_id to your desired display identifier

2. Run the script in your PostgreSQL database

3. The admin user will be created with:
   - Confirmed status (ready to use)
   - Associated display ID for UI purposes
   - Current timestamp for confirmation

4. Test login with the email/password combination

5. After first login, change the password through the application

EXAMPLE:
   admin_email := 'admin@mycompany.com';
   admin_password := 'MySecurePass2024!';
   display_id := 'ADM-000001';
*/