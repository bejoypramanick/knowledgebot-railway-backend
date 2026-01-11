-- ============================================================================
-- SETUP FIRST ADMIN USER (SECURE VERSION)
-- This script configures the first admin user with a randomly generated password
-- Run this after populating email_oauth_credentials table
-- ============================================================================

-- Configure the first admin user with secure random password
DO $$
DECLARE
    admin_email VARCHAR(255) := 'admin@globistaan.com';
    secure_password VARCHAR(255);
BEGIN
    -- Generate a secure random password
    secure_password := 'ADM-' || UPPER(SUBSTRING(MD5(RANDOM()::TEXT) FROM 1 FOR 8)) || '!' || EXTRACT(EPOCH FROM NOW())::INTEGER % 1000;

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

    -- Log the creation with the generated password
    RAISE NOTICE '================================================';
    RAISE NOTICE 'FIRST ADMIN USER CREATED';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Email: %', admin_email;
    RAISE NOTICE 'Password: %', secure_password;
    RAISE NOTICE 'Status: confirmed';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'SAVE THIS PASSWORD - It will only be shown once!';
    RAISE NOTICE '================================================';
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
    created_at,
    LENGTH(auto_generated_password) as password_length
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
    'ADM-' || LPAD(NEXTVAL('user_unique_ids_id_seq')::TEXT, 6, '0'),
    'admin',
    CURRENT_TIMESTAMP
)
ON CONFLICT (email, role) DO NOTHING;

-- ============================================================================
-- SETUP COMPLETE
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '================================================';
    RAISE NOTICE 'ADMIN SETUP COMPLETE';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'The admin user has been created with a secure password.';
    RAISE NOTICE 'Check the output above for the generated password.';
    RAISE NOTICE '================================================';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '1. Save the generated password securely';
    RAISE NOTICE '2. Test admin login through the application';
    RAISE NOTICE '3. Change password after first login';
    RAISE NOTICE '4. Configure additional admin users through the UI';
    RAISE NOTICE '================================================';
END $$;