# Kreuzberg Worker

This service is the dedicated extraction worker for the ingestion pipeline.

## Intended flow

1. File worker or web worker uploads raw content to S3 and creates a presigned URL.
2. They publish an `ExtractionJob` to Redis queue `kreuzberg_extraction_tasks`.
3. This service downloads the source from the presigned URL.
4. It extracts content, performs chunking, uploads structured artifacts back to S3, and publishes an `ExtractionResult`.
5. The original Python worker consumes the result, generates embeddings with the configured model, inserts into pgvector, and updates the database.

## Current state

The service now includes:

- Redis consumer loop
- S3 upload support
- Shared JSON payload contract
- Kreuzberg Rust extraction via `extract_bytes`
- Built-in Kreuzberg chunk generation
- Structured table artifact export
- Result publication back to Redis

What still remains is the Python-side cutover:

- file worker publishes extraction jobs instead of calling the current REST wrapper
- web worker does the same for HTML pages
- those workers consume the extraction result artifacts from S3/Redis, then continue with Gemini embeddings and pgvector insertion

## Environment

- `EXTRACT_REDIS_URL` or `FILE_REDIS_URL`
- `EXTRACT_TASK_QUEUE` optional, defaults to `kreuzberg_extraction_tasks`
- `RAILWAY_STORAGE_URL`
- `RAILWAY_STORAGE_ACCESS_KEY`
- `RAILWAY_STORAGE_SECRET_KEY`
- `RAILWAY_BUCKET_NAME` or `RAILWAY_VOLUME_NAME`
- `RAILWAY_REGION` optional, defaults to `us-east-1`

## Kreuzberg env toggles

These are read directly by the Rust worker so they can be managed from Railway variables.

- `KREUZBERG_ENABLE_QUALITY_PROCESSING` default `true`
- `KREUZBERG_USE_CACHE` default `true`
- `KREUZBERG_INCLUDE_DOCUMENT_STRUCTURE` default `true`
- `KREUZBERG_MAX_CONCURRENT_EXTRACTIONS` optional integer

- `KREUZBERG_CHUNK_MAX_CHARACTERS` default `1200`
- `KREUZBERG_CHUNK_OVERLAP` default `150`

- `KREUZBERG_OCR_ENABLED` default `false`
- `KREUZBERG_FORCE_OCR` default `false`
- `KREUZBERG_OCR_BACKEND` default `tesseract`
- `KREUZBERG_OCR_LANGUAGE` default `eng`
- `KREUZBERG_TESSERACT_PSM` default `3`
- `KREUZBERG_TESSERACT_OEM` default `3`
- `KREUZBERG_TESSERACT_ENABLE_TABLE_DETECTION` default `true`

- `KREUZBERG_LANGUAGE_DETECTION_ENABLED` default `false`
- `KREUZBERG_LANGUAGE_DETECTION_MIN_CONFIDENCE` default `0.8`
- `KREUZBERG_LANGUAGE_DETECTION_DETECT_MULTIPLE` default `false`

- `KREUZBERG_PAGE_EXTRACT_PAGES` default `true`
- `KREUZBERG_PAGE_INSERT_MARKERS` default `false`
- `KREUZBERG_PAGE_MARKER_FORMAT` default `\n\n<!-- PAGE {page_num} -->\n\n`

- `KREUZBERG_PDF_ALLOW_SINGLE_COLUMN_TABLES` default `false`
- `KREUZBERG_PDF_EXTRACT_IMAGES` default `false`
- `KREUZBERG_PDF_EXTRACT_METADATA` default `true`
- `KREUZBERG_PDF_PASSWORDS` optional comma-separated passwords

- `KREUZBERG_IMAGE_EXTRACTION_ENABLED` default `false`
- `KREUZBERG_IMAGE_TARGET_DPI` default `300`
- `KREUZBERG_IMAGE_MAX_DIMENSION` default `4096`
- `KREUZBERG_IMAGE_AUTO_ADJUST_DPI` default `true`
- `KREUZBERG_IMAGE_MIN_DPI` default `72`
- `KREUZBERG_IMAGE_MAX_DPI` default `600`

Note: the current Rust worker exposes OCR/layout-related controls supported by the `kreuzberg 4.6.1` Rust API. There is no separate generic `vision_model` field in the worker today; OCR backend and related extraction settings are the main Railway-controlled knobs.
