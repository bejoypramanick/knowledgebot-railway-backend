BEGIN;

ALTER TABLE file_uploads
    RENAME COLUMN gemini_file_name TO storage_document_name;

ALTER TABLE file_uploads
    RENAME COLUMN gemini_file_uri TO storage_document_uri;

ALTER TABLE file_uploads
    RENAME COLUMN gemini_state TO storage_backend_state;

ALTER TABLE scraped_websites
    RENAME COLUMN gemini_file_name TO storage_document_name;

ALTER TABLE scraped_websites
    RENAME COLUMN gemini_file_uri TO storage_document_uri;

ALTER TABLE scraped_websites
    RENAME COLUMN gemini_state TO storage_backend_state;

ALTER INDEX IF EXISTS idx_file_uploads_completed_lookup
    RENAME TO idx_file_uploads_completed_storage_lookup;

ALTER INDEX IF EXISTS idx_file_uploads_gemini_sync
    RENAME TO idx_file_uploads_storage_sync;

COMMIT;
