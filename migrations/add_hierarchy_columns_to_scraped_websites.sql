-- Add Hierarchy Columns for Hierarchical Tree View Support
-- Purpose: Track parent-child relationships for website scraping to display citations in tree structure
-- Created: 2026-02-12
-- Migration adds columns to enable hierarchical organization of scraped pages

-- Add hierarchy-related columns to scraped_websites table
ALTER TABLE scraped_websites
ADD COLUMN parent_id integer REFERENCES scraped_websites(id) ON DELETE CASCADE,
ADD COLUMN depth integer DEFAULT 0 NOT NULL,
ADD COLUMN crawl_session_id uuid;

-- Add indexes for performance
-- parent_id index: for querying children of a parent page
CREATE INDEX idx_scraped_websites_parent_id
ON scraped_websites(parent_id);

-- crawl_session_id index: for grouping pages from same scraping session
CREATE INDEX idx_scraped_websites_crawl_session_id
ON scraped_websites(crawl_session_id);

-- depth index: for querying by hierarchy level
CREATE INDEX idx_scraped_websites_depth
ON scraped_websites(depth);

-- Composite index: useful for querying children of a session
CREATE INDEX idx_scraped_websites_session_parent
ON scraped_websites(crawl_session_id, parent_id);

-- Analyze table to update statistics after adding columns
ANALYZE scraped_websites;

-- Add comment to columns for documentation
COMMENT ON COLUMN scraped_websites.parent_id IS 'ID of the parent page in the hierarchy (NULL for root pages)';
COMMENT ON COLUMN scraped_websites.depth IS 'Depth in hierarchy: 0=root, 1=direct child, 2=grandchild, etc.';
COMMENT ON COLUMN scraped_websites.crawl_session_id IS 'UUID to group pages from the same scraping session';
