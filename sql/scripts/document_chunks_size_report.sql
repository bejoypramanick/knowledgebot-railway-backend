-- ==============================================================================
-- Document Chunks Size Report
-- ==============================================================================
-- Calculates the size of document_chunks content in KB for each file uploaded
-- or website scraped, along with the number of chunks.
-- ==============================================================================

-- 1. File Uploads with their chunk sizes and counts
SELECT 
    'file_uploads' AS source_type,
    fu.id AS source_id,
    fu.tenant_id,
    t.slug AS tenant_slug,
    t.name AS tenant_name,
    fu.file_name,
    fu.file_size / 1024.0 AS original_file_size_kb,
    COUNT(dc.id) AS chunk_count,
    ROUND(LENGTH(string_agg(dc.content, '')) / 1024.0, 2) AS chunks_size_kb,
    ROUND((LENGTH(string_agg(dc.content, '')) / 1024.0) / NULLIF(COUNT(dc.id), 0), 2) AS avg_chunk_size_kb,
    fu.processing_status,
    fu.created_at
FROM file_uploads fu
LEFT JOIN document_chunks dc ON dc.file_id = fu.id
LEFT JOIN tenants t ON t.id = fu.tenant_id
WHERE fu.processing_status = 'completed'
GROUP BY fu.id, fu.tenant_id, t.slug, t.name, fu.file_name, fu.file_size, fu.processing_status, fu.created_at
ORDER BY chunks_size_kb DESC NULLS LAST;

-- 2. Scraped Websites with their chunk sizes and counts
SELECT 
    'scraped_websites' AS source_type,
    sw.id AS source_id,
    sw.tenant_id,
    t.slug AS tenant_slug,
    t.name AS tenant_name,
    sw.url AS website_url,
    sw.content_length / 1024.0 AS original_content_size_kb,
    COUNT(dc.id) AS chunk_count,
    ROUND(LENGTH(string_agg(dc.content, '')) / 1024.0, 2) AS chunks_size_kb,
    ROUND((LENGTH(string_agg(dc.content, '')) / 1024.0) / NULLIF(COUNT(dc.id), 0), 2) AS avg_chunk_size_kb,
    sw.processing_status,
    sw.created_at
FROM scraped_websites sw
LEFT JOIN document_chunks dc ON dc.website_id = sw.id
LEFT JOIN tenants t ON t.id = sw.tenant_id
WHERE sw.processing_status = 'completed'
  AND sw.parent_id IS NULL
GROUP BY sw.id, sw.tenant_id, t.slug, t.name, sw.url, sw.content_length, sw.processing_status, sw.created_at
ORDER BY chunks_size_kb DESC NULLS LAST;

-- 3. Summary by Tenant
SELECT 
    t.id AS tenant_id,
    t.slug AS tenant_slug,
    t.name AS tenant_name,
    COUNT(DISTINCT fu.id) AS total_files,
    COUNT(DISTINCT sw.id) AS total_websites,
    COALESCE(SUM(fu.file_size), 0) / 1024.0 AS total_original_size_kb,
    COUNT(dc.id) AS total_chunks,
    ROUND(LENGTH(string_agg(dc.content, '')) / 1024.0, 2) AS total_chunks_size_kb
FROM tenants t
LEFT JOIN file_uploads fu ON fu.tenant_id = t.id AND fu.processing_status = 'completed'
LEFT JOIN scraped_websites sw ON sw.tenant_id = t.id AND sw.processing_status = 'completed' AND sw.parent_id IS NULL
LEFT JOIN document_chunks dc ON dc.file_id = fu.id OR dc.website_id = sw.id
GROUP BY t.id, t.slug, t.name
ORDER BY total_chunks_size_kb DESC NULLS LAST;

-- 4. Grand Total
SELECT 
    'TOTAL' AS tenant_slug,
    COUNT(DISTINCT fu.id) AS total_files,
    COUNT(DISTINCT sw.id) AS total_websites,
    COALESCE(SUM(fu.file_size), 0) / 1024.0 AS total_original_size_kb,
    COUNT(dc.id) AS total_chunks,
    ROUND(LENGTH(string_agg(dc.content, '')) / 1024.0, 2) AS total_chunks_size_kb
FROM file_uploads fu
LEFT JOIN scraped_websites sw ON sw.tenant_id = fu.tenant_id AND sw.processing_status = 'completed' AND sw.parent_id IS NULL
LEFT JOIN document_chunks dc ON dc.file_id = fu.id OR dc.website_id = sw.id
WHERE fu.processing_status = 'completed';
