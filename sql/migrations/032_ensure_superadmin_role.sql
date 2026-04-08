BEGIN;

INSERT INTO public.roles (role_name, role_description, created_at, updated_at)
VALUES (
    'superadmin',
    'Platform-level administrator allowed to provision tenants and seed tenant admins',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (role_name)
DO UPDATE SET
    role_description = EXCLUDED.role_description,
    updated_at = CURRENT_TIMESTAMP;

COMMIT;
