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
