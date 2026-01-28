-- Migration 005: Create agent_session_assignments table
-- This table manages assignments of human agents to chat sessions

CREATE TABLE IF NOT EXISTS public.agent_session_assignments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    agent_id uuid NOT NULL,
    assigned_at timestamp DEFAULT now() NULL,
    status varchar(50) DEFAULT 'active' NOT NULL,
    assigned_by_email varchar(255) NULL,
    ended_at timestamp NULL,
    CONSTRAINT agent_session_assignments_pkey PRIMARY KEY (id),
    CONSTRAINT valid_assignment_status CHECK (status IN ('waiting', 'active', 'transferred', 'ended')),
    CONSTRAINT agent_session_assignments_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    CONSTRAINT agent_session_assignments_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.human_agents(id) ON DELETE CASCADE
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_session_assignments_session_id ON public.agent_session_assignments USING btree (session_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_agent_id ON public.agent_session_assignments USING btree (agent_id);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status ON public.agent_session_assignments USING btree (status);
CREATE INDEX IF NOT EXISTS idx_session_assignments_status_updated ON public.agent_session_assignments USING btree (status, assigned_at DESC);

-- Add comments
COMMENT ON TABLE public.agent_session_assignments IS 'Assignments of human agents to chat sessions';
COMMENT ON COLUMN public.agent_session_assignments.session_id IS 'ID of the chat session';
COMMENT ON COLUMN public.agent_session_assignments.agent_id IS 'ID of the assigned human agent';
COMMENT ON COLUMN public.agent_session_assignments.assigned_at IS 'When the assignment was made';
COMMENT ON COLUMN public.agent_session_assignments.status IS 'Assignment status: waiting (pending), active (currently handling), transferred (moved to another agent), ended (completed)';
COMMENT ON COLUMN public.agent_session_assignments.assigned_by_email IS 'Email of the admin who made the assignment';
COMMENT ON COLUMN public.agent_session_assignments.ended_at IS 'When the assignment ended';

-- Create trigger for updated_at (if needed in future)
-- Note: This table doesn't have updated_at column, but keeping the pattern for consistency
