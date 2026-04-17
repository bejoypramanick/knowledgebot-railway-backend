SELECT 
    dc.document_id,
    COALESCE(fu.tenant_id, sw.tenant_id) AS tenant_id,
    COALESCE(MAX(fu.original_filename), MAX(sw.original_url)) AS name,
    COALESCE(MAX(fu.processing_status), MAX(sw.processing_status)) AS status,
    COUNT(dc.id) AS rows_count,
    ROUND(SUM(LENGTH(dc.content)) / 1024.0, 2) AS total_db_kb
FROM document_chunks dc
LEFT JOIN file_uploads fu ON fu.id = dc.document_id AND fu.processing_status IN ('completed', 'deleted')
LEFT JOIN scraped_websites sw ON sw.id = dc.document_id AND sw.processing_status IN ('completed', 'deleted')
GROUP BY dc.document_id, fu.tenant_id, sw.tenant_id
ORDER BY total_db_kb DESC;