    -- Migration: 049_rename_filestore_columns_to_embedding_counts
    -- Description:
    --   We no longer use Gemini File Store. Rename the legacy filestore counters on
    --   file_uploads and scraped_websites so they represent the chunk payload sent
    --   for embeddings instead. Also backfill character/word counts from
    --   document_chunks for existing records where chunk content is present.

    ALTER TABLE public.file_uploads
        RENAME COLUMN filestore_character_count TO embedding_character_count;

    ALTER TABLE public.file_uploads
        RENAME COLUMN filestore_word_count TO embedding_word_count;

    ALTER TABLE public.file_uploads
        RENAME COLUMN filestore_token_count TO embedding_token_count;

    ALTER TABLE public.scraped_websites
        RENAME COLUMN filestore_character_count TO embedding_character_count;

    ALTER TABLE public.scraped_websites
        RENAME COLUMN filestore_word_count TO embedding_word_count;

    ALTER TABLE public.scraped_websites
        RENAME COLUMN filestore_token_count TO embedding_token_count;

    WITH file_chunk_stats AS (
        SELECT
            dc.document_id,
            COALESCE(SUM(char_length(dc.content)), 0)::INTEGER AS embedding_character_count,
            COALESCE(SUM(
                CASE
                    WHEN btrim(dc.content) = '' THEN 0
                    ELSE cardinality(regexp_split_to_array(btrim(dc.content), E'\\s+'))
                END
            ), 0)::INTEGER AS embedding_word_count
        FROM public.document_chunks dc
        WHERE dc.document_type = 'file'
        GROUP BY dc.document_id
    )
    UPDATE public.file_uploads fu
    SET
        embedding_character_count = file_chunk_stats.embedding_character_count,
        embedding_word_count = file_chunk_stats.embedding_word_count
    FROM file_chunk_stats
    WHERE fu.id = file_chunk_stats.document_id;

    WITH website_chunk_stats AS (
        SELECT
            dc.document_id,
            COALESCE(SUM(char_length(dc.content)), 0)::INTEGER AS embedding_character_count,
            COALESCE(SUM(
                CASE
                    WHEN btrim(dc.content) = '' THEN 0
                    ELSE cardinality(regexp_split_to_array(btrim(dc.content), E'\\s+'))
                END
            ), 0)::INTEGER AS embedding_word_count
        FROM public.document_chunks dc
        WHERE dc.document_type = 'website'
        GROUP BY dc.document_id
    )
    UPDATE public.scraped_websites sw
    SET
        embedding_character_count = website_chunk_stats.embedding_character_count,
        embedding_word_count = website_chunk_stats.embedding_word_count
    FROM website_chunk_stats
    WHERE sw.id = website_chunk_stats.document_id;
