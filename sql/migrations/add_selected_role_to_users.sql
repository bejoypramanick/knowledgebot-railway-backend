-- Add selected_role column to users table to store user's current role preference
ALTER TABLE public.users
ADD COLUMN selected_role VARCHAR(50) DEFAULT NULL;

-- Add comment explaining the column
COMMENT ON COLUMN public.users.selected_role IS 'User''s currently selected role for UI navigation (admin, agent, customer)';

-- Create index for faster lookups
CREATE INDEX idx_users_selected_role ON public.users(selected_role);
