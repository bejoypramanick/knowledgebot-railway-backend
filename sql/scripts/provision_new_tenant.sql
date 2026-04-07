-- ==============================================================================
-- 🚀  LAZY PROVISIONING SCRIPT 
-- ==============================================================================
-- Description: 
-- This script whitelists a new user. You no longer need to manually provision
-- tenants, mapping, or configuration defaults beforehand. The backend API handles this
-- automatically on their VERY FIRST login out-of-the-box!
-- ==============================================================================

BEGIN;

DO $$
DECLARE
    -- ⬇️ EDIT THIS VARIABLE ⬇️
    v_admin_email text := 'newadmin@yourcompany.com';
    -- ⬆️ EDIT THIS VARIABLE ⬆️
    
    v_user_id uuid;
BEGIN
    RAISE NOTICE '⚡ Whitelisting Admin: %', v_admin_email;

    -- 1. Upsert the user into the system
    INSERT INTO public.users (email, is_active, created_at, updated_at)
    VALUES (v_admin_email, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ON CONFLICT (email)
        DO UPDATE SET is_active = true, updated_at = CURRENT_TIMESTAMP
    RETURNING id INTO v_user_id;

    RAISE NOTICE '✅ User whitelisted successfully: % (id=%)', v_admin_email, v_user_id;
    RAISE NOTICE '👉 They will be automatically provisioned with a tenant and admin roles upon first login.';

END $$;

COMMIT;
