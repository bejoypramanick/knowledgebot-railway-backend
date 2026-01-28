-- Migration 007: Create widget_configuration table
-- This table stores configuration for the chat widget

CREATE TABLE IF NOT EXISTS public.widget_configuration (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    widget_title varchar(200) DEFAULT 'KnowledgeBot Assistant' NOT NULL,
    primary_color varchar(20) DEFAULT '#007bff' NOT NULL,
    secondary_color varchar(20) DEFAULT '#6c757d' NOT NULL,
    background_color varchar(20) DEFAULT '#ffffff' NOT NULL,
    text_color varchar(20) DEFAULT '#333333' NOT NULL,
    border_color varchar(20) DEFAULT '#dee2e6' NOT NULL,
    border_radius integer DEFAULT 8 NOT NULL,
    widget_width integer DEFAULT 350 NOT NULL,
    widget_height integer DEFAULT 500 NOT NULL,
    position_x integer DEFAULT 20 NOT NULL,
    position_y integer DEFAULT 20 NOT NULL,
    profile_zoom integer DEFAULT 100 NOT NULL,
    chat_icon_zoom integer DEFAULT 100 NOT NULL,
    profile_position varchar(20) DEFAULT 'bottom-right' NOT NULL,
    chat_icon_position varchar(20) DEFAULT 'bottom-right' NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp DEFAULT now() NULL,
    updated_at timestamp DEFAULT now() NULL,
    updated_by_email varchar(255) NULL,
    CONSTRAINT widget_configuration_pkey PRIMARY KEY (id),
    CONSTRAINT valid_border_radius CHECK (border_radius >= 0 AND border_radius <= 50),
    CONSTRAINT valid_widget_dimensions CHECK (widget_width > 0 AND widget_height > 0),
    CONSTRAINT valid_zoom_levels CHECK (profile_zoom >= 50 AND profile_zoom <= 200),
    CONSTRAINT valid_zoom_levels_chat CHECK (chat_icon_zoom >= 50 AND chat_icon_zoom <= 200),
    CONSTRAINT valid_position CHECK (profile_position IN ('top-left', 'top-right', 'bottom-left', 'bottom-right')),
    CONSTRAINT valid_icon_position CHECK (chat_icon_position IN ('top-left', 'top-right', 'bottom-left', 'bottom-right'))
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_widget_configuration_active ON public.widget_configuration USING btree (is_active);

-- Add comments
COMMENT ON TABLE public.widget_configuration IS 'Configuration settings for the chat widget appearance and behavior';
COMMENT ON COLUMN public.widget_configuration.widget_title IS 'Title displayed in the widget header';
COMMENT ON COLUMN public.widget_configuration.primary_color IS 'Primary color for buttons and highlights';
COMMENT ON COLUMN public.widget_configuration.secondary_color IS 'Secondary color for UI elements';
COMMENT ON COLUMN public.widget_configuration.background_color IS 'Background color of the widget';
COMMENT ON COLUMN public.widget_configuration.text_color IS 'Text color for messages and labels';
COMMENT ON COLUMN public.widget_configuration.border_color IS 'Color of widget borders';
COMMENT ON COLUMN public.widget_configuration.border_radius IS 'Border radius in pixels (0-50)';
COMMENT ON COLUMN public.widget_configuration.widget_width IS 'Widget width in pixels';
COMMENT ON COLUMN public.widget_configuration.widget_height IS 'Widget height in pixels';
COMMENT ON COLUMN public.widget_configuration.position_x IS 'Horizontal position from edge in pixels';
COMMENT ON COLUMN public.widget_configuration.position_y IS 'Vertical position from edge in pixels';
COMMENT ON COLUMN public.widget_configuration.profile_zoom IS 'Zoom level for profile avatar (50-200%)';
COMMENT ON COLUMN public.widget_configuration.chat_icon_zoom IS 'Zoom level for chat icon (50-200%)';
COMMENT ON COLUMN public.widget_configuration.profile_position IS 'Position of profile picture';
COMMENT ON COLUMN public.widget_configuration.chat_icon_position IS 'Position of chat icon';
COMMENT ON COLUMN public.widget_configuration.is_active IS 'Whether this configuration is currently active';
COMMENT ON COLUMN public.widget_configuration.updated_by_email IS 'Email of the admin who last updated this configuration';

-- Insert default widget configuration
INSERT INTO public.widget_configuration (
    widget_title, primary_color, secondary_color, background_color, text_color,
    border_color, border_radius, widget_width, widget_height, position_x, position_y,
    profile_zoom, chat_icon_zoom, profile_position, chat_icon_position, is_active, updated_by_email
)
VALUES (
    'KnowledgeBot Assistant', '#007bff', '#6c757d', '#ffffff', '#333333',
    '#dee2e6', 8, 350, 500, 20, 20,
    100, 100, 'bottom-right', 'bottom-right', true, 'system@knowledgebot.com'
) ON CONFLICT DO NOTHING;

-- Create trigger for updated_at
CREATE OR REPLACE FUNCTION public.update_widget_configuration_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language plpgsql;

CREATE TRIGGER widget_configuration_updated_at
    BEFORE UPDATE ON public.widget_configuration
    FOR EACH ROW
    EXECUTE FUNCTION public.update_widget_configuration_updated_at();
