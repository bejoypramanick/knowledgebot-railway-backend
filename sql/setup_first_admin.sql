-- ============================================================================
-- SETUP FIRST ADMIN USER
-- This script configures the first admin user in the database
-- Run this after populating email_oauth_credentials table
-- ============================================================================

-- Generate a secure password for the first admin
-- In production, you should generate a proper secure password
DO $$
DECLARE
    admin_email VARCHAR(255) := 'admin@globistaan.com';
    secure_password VARCHAR(255) := 'AdminSecurePass123!'; -- Change this to a secure password
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
        secure_password,
        CURRENT_TIMESTAMP,
        NULL  -- First admin has no creator
    )
    ON CONFLICT (email) DO UPDATE SET
        status = 'confirmed',
        auto_generated_password = EXCLUDED.auto_generated_password,
        confirmed_at = CURRENT_TIMESTAMP;

    -- Log the creation
    RAISE NOTICE 'First admin user configured: %', admin_email;
    RAISE NOTICE 'Password: %', secure_password;
    RAISE NOTICE 'Status: confirmed';
END $$;

-- ============================================================================
-- VERIFY ADMIN CREATION
-- ============================================================================

-- Check that the admin was created
SELECT
    id,
    email,
    status,
    confirmed_at,
    created_at
FROM admins
WHERE email = 'admin@globistaan.com';

-- ============================================================================
-- OPTIONAL: Create user_unique_id for the admin (for display purposes)
-- ============================================================================

INSERT INTO user_unique_ids (
    email,
    unique_id,
    role,
    created_at
)
VALUES (
    'admin@globistaan.com',
    'ADM-000001',
    'admin',
    CURRENT_TIMESTAMP
)
ON CONFLICT (email, role) DO NOTHING;

-- ============================================================================
-- SETUP COMPLETE
-- ============================================================================

-- Display completion message
DO $$
BEGIN
    RAISE NOTICE '================================================';
    RAISE NOTICE 'FIRST ADMIN SETUP COMPLETE';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Admin Email: admin@globistaan.com';
    RAISE NOTICE 'Password: AdminSecurePass123! (CHANGE THIS!)';
    RAISE NOTICE 'Status: confirmed';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Change the default password to something secure';
    RAISE NOTICE '2. Test admin login through the application';
    RAISE NOTICE '3. Configure additional admin users through the UI';
    RAISE NOTICE '================================================';
END $$;