-- Migration 001: Add missing columns to existing tables
-- This script adds missing columns that are referenced in the code but don't exist in the database

-- Add status column to admins table
ALTER TABLE public.admins 
ADD COLUMN IF NOT EXISTS status varchar(50) DEFAULT 'active' NOT NULL;

-- Add constraint for status column
ALTER TABLE public.admins 
ADD CONSTRAINT IF NOT EXISTS admins_status_check 
CHECK (status IN ('active', 'inactive', 'removed'));

-- Create index for status column
CREATE INDEX IF NOT EXISTS idx_admins_status ON public.admins USING btree (status);

-- Add comments
COMMENT ON COLUMN public.admins.status IS 'Admin status: active (can access), inactive (suspended), removed (deleted)';
