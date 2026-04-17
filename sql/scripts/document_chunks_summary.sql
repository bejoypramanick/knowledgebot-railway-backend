-- Document chunks summary per file and website
SELECT 
    source_id,
    source_type,
    tenant_id,
    COUNT(chunk_id) AS chunk_count,
    ROUND(SUM(content_length) / 1024.0, 2) AS total_kb
FROM (
    SELECT 
        fu.id AS source_id,
        'file' AS source_type,
        fu.tenant_id,
        dc.id AS chunk_id,
        LENGTH(dc.content) AS content_length
    FROM file_uploads fu
    LEFT JOIN document_chunks dc ON dc.file_id = fu.id
    WHERE fu.processing_status != 'deleted'
    
    UNION ALL
    
    SELECT 
        sw.id AS source_id,
        'website' AS source_type,
        sw.tenant_id,
        dc.id AS chunk_id,
        LENGTH(dc.content) AS content_length
    FROM scraped_websites sw
    LEFT JOIN document_chunks dc ON dc.website_id = sw.id
    WHERE sw.processing_status != 'deleted'
      AND sw.parent_id IS NULL
) combined
GROUP BY source_id, source_type, tenant_id
ORDER BY total_kb DESC;
