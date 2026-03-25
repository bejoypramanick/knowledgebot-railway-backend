use anyhow::{anyhow, Context, Result};
use aws_config::BehaviorVersion;
use aws_credential_types::Credentials;
use aws_sdk_s3::{config::Region, primitives::ByteStream, Client as S3Client};
use chrono::Utc;
use kreuzberg::{
    detect_mime_type_from_bytes, extract_bytes, validate_mime_type, ChunkingConfig, ChunkerType,
    ExtractionConfig, ImageExtractionConfig, LanguageDetectionConfig, OcrConfig,
    OutputFormat as ContentOutputFormat, PageConfig, PdfConfig, Table, TesseractConfig,
};
use redis::Commands;
use reqwest::Client as HttpClient;
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::env;
use std::time::Duration;
use tracing::{error, info};

const DEFAULT_TASK_QUEUE: &str = "kreuzberg_extraction_tasks";
const DEFAULT_RESULT_QUEUE: &str = "kreuzberg_extraction_results";

#[derive(Debug, Deserialize)]
struct ExtractionJob {
    job_id: String,
    document_id: String,
    presigned_url: String,
    artifact_prefix: String,
    #[serde(default = "default_result_queue")]
    reply_channel: String,
}

#[derive(Debug, Serialize)]
struct ExtractionResult {
    job_id: String,
    document_id: String,
    status: String,
    manifest_s3_key: Option<String>,
    error: Option<String>,
    completed_at: String,
}

#[derive(Debug, Serialize)]
struct ExtractedChunk {
    text: String,
    metadata: serde_json::Value,
}

#[derive(Clone)]
struct AppState {
    redis_client: redis::Client,
    s3_client: S3Client,
    http_client: HttpClient,
    bucket_name: String,
    task_queue: String,
}

fn default_result_queue() -> String {
    DEFAULT_RESULT_QUEUE.to_string()
}

#[tokio::main]
async fn main() -> Result<()> {
    init_tracing();

    let state = build_state().await?;
    info!("kreuzberg-worker started");

    loop {
        match pop_job(&state) {
            Ok(Some(job)) => {
                if let Err(err) = handle_job(&state, job).await {
                    error!("job handling failed: {err:#}");
                }
            }
            Ok(None) => {}
            Err(err) => {
                error!("redis pop failed: {err:#}");
                tokio::time::sleep(Duration::from_secs(2)).await;
            }
        }
    }
}

fn init_tracing() {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,aws_config=warn,aws_sdk_s3=warn,redis=warn".into()),
        )
        .init();
}

async fn build_state() -> Result<AppState> {
    let redis_url = env_var("EXTRACT_REDIS_URL")
        .or_else(|_| env_var("FILE_REDIS_URL"))
        .context("missing EXTRACT_REDIS_URL or FILE_REDIS_URL")?;
    let task_queue = env::var("EXTRACT_TASK_QUEUE").unwrap_or_else(|_| DEFAULT_TASK_QUEUE.to_string());
    let bucket_name = env::var("RAILWAY_BUCKET_NAME")
        .or_else(|_| env::var("RAILWAY_VOLUME_NAME"))
        .unwrap_or_else(|_| "knowledgebot-storage".to_string());

    let endpoint_url = env_var("RAILWAY_STORAGE_URL")?;
    let access_key = env_var("RAILWAY_STORAGE_ACCESS_KEY")?;
    let secret_key = env_var("RAILWAY_STORAGE_SECRET_KEY")?;
    let region = env::var("RAILWAY_REGION").unwrap_or_else(|_| "us-east-1".to_string());

    let redis_client = redis::Client::open(redis_url.clone())
        .with_context(|| format!("invalid redis url: {redis_url}"))?;

    let creds = Credentials::new(access_key, secret_key, None, None, "railway-storage");
    let shared_config = aws_config::defaults(BehaviorVersion::latest())
        .region(Region::new(region))
        .credentials_provider(creds)
        .load()
        .await;

    let s3_config = aws_sdk_s3::config::Builder::from(&shared_config)
        .endpoint_url(endpoint_url)
        .force_path_style(true)
        .build();

    let s3_client = S3Client::from_conf(s3_config);
    let http_client = HttpClient::builder()
        .timeout(Duration::from_secs(300))
        .build()
        .context("failed to build http client")?;

    Ok(AppState {
        redis_client,
        s3_client,
        http_client,
        bucket_name,
        task_queue,
    })
}

fn pop_job(state: &AppState) -> Result<Option<ExtractionJob>> {
    let mut conn = state.redis_client.get_connection()?;
    let result: Option<(String, String)> = redis::cmd("BLPOP")
        .arg(&state.task_queue)
        .arg(5)
        .query(&mut conn)?;

    if let Some((_queue, payload)) = result {
        let job: ExtractionJob = serde_json::from_str(&payload).context("invalid extraction payload")?;
        info!(
            job_id = %job.job_id,
            document_id = %job.document_id,
            "received extraction job"
        );
        Ok(Some(job))
    } else {
        Ok(None)
    }
}

async fn handle_job(state: &AppState, job: ExtractionJob) -> Result<()> {
    let result = match process_job(state, &job).await {
        Ok(success) => success,
        Err(err) => {
            error!(job_id = %job.job_id, "extraction failed: {err:#}");
            ExtractionResult {
                job_id: job.job_id.clone(),
                document_id: job.document_id.clone(),
                status: "failed".to_string(),
                manifest_s3_key: None,
                error: Some(err.to_string()),
                completed_at: Utc::now().to_rfc3339(),
            }
        }
    };

    publish_result(state, &job.reply_channel, &result)?;
    Ok(())
}

async fn process_job(state: &AppState, job: &ExtractionJob) -> Result<ExtractionResult> {
    let file_bytes = download_from_presigned_url(state, &job.presigned_url).await?;
    let extraction = extract_and_chunk(&file_bytes).await?;

    let markdown_key = upload_bytes(
        state,
        &format!("{}.md", job.artifact_prefix),
        extraction.markdown.as_bytes().to_vec(),
        "text/markdown; charset=utf-8",
    )
    .await?;

    let chunks_key = upload_bytes(
        state,
        &format!("{}_chunks.json", job.artifact_prefix),
        serde_json::to_vec_pretty(&extraction.chunks)?,
        "application/json",
    )
    .await?;

    let tables_key = if extraction.tables.is_null() {
        None
    } else {
        Some(
            upload_bytes(
                state,
                &format!("{}_tables.json", job.artifact_prefix),
                serde_json::to_vec_pretty(&extraction.tables)?,
                "application/json",
            )
            .await?,
        )
    };

    let manifest = json!({
        "job_id": job.job_id,
        "document_id": job.document_id,
        "markdown_s3_key": markdown_key,
        "chunks_s3_key": chunks_key,
        "tables_s3_key": tables_key,
        "metadata": extraction.metadata,
    });

    let manifest_key = upload_bytes(
        state,
        &format!("{}_manifest.json", job.artifact_prefix),
        serde_json::to_vec_pretty(&manifest)?,
        "application/json",
    )
    .await?;

    Ok(ExtractionResult {
        job_id: job.job_id.clone(),
        document_id: job.document_id.clone(),
        status: "completed".to_string(),
        manifest_s3_key: Some(manifest_key),
        error: None,
        completed_at: Utc::now().to_rfc3339(),
    })
}

async fn download_from_presigned_url(state: &AppState, presigned_url: &str) -> Result<Vec<u8>> {
    let response = state
        .http_client
        .get(presigned_url)
        .send()
        .await
        .context("failed to download presigned url")?
        .error_for_status()
        .context("presigned url returned error status")?;

    let body = response.bytes().await.context("failed to read response body")?;
    Ok(body.to_vec())
}

struct ExtractionArtifacts {
    markdown: String,
    chunks: Vec<ExtractedChunk>,
    tables: serde_json::Value,
    metadata: serde_json::Value,
}

async fn extract_and_chunk(file_bytes: &[u8]) -> Result<ExtractionArtifacts> {
    let checksum = checksum(file_bytes);
    let mime_type = detect_mime_type_from_bytes(file_bytes)
        .or_else(|_| validate_mime_type("application/octet-stream"))
        .context("unable to validate or detect mime type for extraction")?;
    let extraction_config = build_extraction_config();
    let chunk_size = extraction_config
        .chunking
        .as_ref()
        .map(|cfg| cfg.max_characters)
        .unwrap_or(1200);
    let chunk_overlap = extraction_config
        .chunking
        .as_ref()
        .map(|cfg| cfg.overlap)
        .unwrap_or(150);

    let result = extract_bytes(file_bytes, &mime_type, &extraction_config)
        .await
        .context("kreuzberg extract_bytes failed")?;

    let enriched_tables = build_table_artifacts(&result.tables, chunk_size);
    let markdown = inject_table_kv_sections(&result.content, &enriched_tables);
    let page_count = result.pages.as_ref().map(|pages| pages.len()).unwrap_or(0);

    let mut chunking_config = extraction_config.clone();
    chunking_config.chunking = Some(ChunkingConfig {
        max_characters: chunk_size,
        overlap: chunk_overlap,
        chunker_type: ChunkerType::Markdown,
        ..Default::default()
    });
    chunking_config.output_format = ContentOutputFormat::Markdown;

    let chunked_markdown = extract_bytes(markdown.as_bytes(), "text/markdown", &chunking_config)
        .await
        .context("kreuzberg markdown chunking failed")?;

    let chunks = chunked_markdown
        .chunks
        .map(|result_chunks| {
            result_chunks
                .into_iter()
                .enumerate()
                .map(|(idx, chunk)| ExtractedChunk {
                    text: chunk.content.clone(),
                    metadata: json!({
                        "chunk_index": idx,
                        "byte_start": chunk.metadata.byte_start,
                        "byte_end": chunk.metadata.byte_end,
                        "char_count": chunk.content.chars().count(),
                        "token_count": chunk.metadata.token_count,
                        "first_page": chunk.metadata.first_page,
                        "last_page": chunk.metadata.last_page,
                        "strategy": "kreuzberg_markdown_table_aware",
                    }),
                })
                .collect::<Vec<_>>()
        })
        .filter(|items| !items.is_empty())
        .unwrap_or_else(|| {
            vec![ExtractedChunk {
                text: markdown.clone(),
                metadata: json!({
                    "chunk_index": 0,
                    "char_count": markdown.chars().count(),
                    "strategy": "kreuzberg_markdown_table_aware",
                }),
            }]
        });

    let tables = serde_json::Value::Array(
        enriched_tables
            .iter()
            .map(|table| {
                json!({
                    "table_index": table.table_index,
                    "page_number": table.page_number,
                    "markdown": table.original_markdown,
                    "kv_markdown": table.kv_markdown,
                    "row_chunks": table.row_chunks,
                    "headers": table.headers,
                    "cells": table.cells,
                    "row_count": table.row_count,
                    "column_count": table.column_count,
                })
            })
            .collect::<Vec<_>>(),
    );

    let metadata = json!({
        "mime_type": mime_type,
        "downloaded_bytes": file_bytes.len(),
        "checksum_sha256": checksum,
        "content_length": markdown.len(),
        "chunk_count": chunks.len(),
        "table_count": tables.as_array().map(|items| items.len()).unwrap_or(0),
        "page_count": page_count,
        "detected_languages": result.detected_languages,
        "document_structure_included": result.document.is_some(),
        "table_kv_enabled": true,
        "table_aware_chunking_enabled": true,
    });

    Ok(ExtractionArtifacts { markdown, chunks, tables, metadata })
}

fn build_extraction_config() -> ExtractionConfig {
    let ocr_enabled = parse_env_bool("KREUZBERG_OCR_ENABLED", false);
    let force_ocr = parse_env_bool("KREUZBERG_FORCE_OCR", false);
    let detect_languages = parse_env_bool("KREUZBERG_LANGUAGE_DETECTION_ENABLED", false);
    let extract_images = parse_env_bool("KREUZBERG_IMAGE_EXTRACTION_ENABLED", false);
    let extract_pages = parse_env_bool("KREUZBERG_PAGE_EXTRACT_PAGES", true);
    let insert_page_markers = parse_env_bool("KREUZBERG_PAGE_INSERT_MARKERS", false);

    let ocr = if ocr_enabled {
        Some(OcrConfig {
            backend: env::var("KREUZBERG_OCR_BACKEND").unwrap_or_else(|_| "tesseract".to_string()),
            language: env::var("KREUZBERG_OCR_LANGUAGE").unwrap_or_else(|_| "eng".to_string()),
            tesseract_config: Some(TesseractConfig {
                psm: parse_env_i32("KREUZBERG_TESSERACT_PSM", 3),
                oem: parse_env_i32("KREUZBERG_TESSERACT_OEM", 3),
                enable_table_detection: parse_env_bool("KREUZBERG_TESSERACT_ENABLE_TABLE_DETECTION", true),
                ..Default::default()
            }),
            ..Default::default()
        })
    } else {
        None
    };

    let language_detection = if detect_languages {
        Some(LanguageDetectionConfig {
            enabled: true,
            min_confidence: parse_env_f64("KREUZBERG_LANGUAGE_DETECTION_MIN_CONFIDENCE", 0.8),
            detect_multiple: parse_env_bool("KREUZBERG_LANGUAGE_DETECTION_DETECT_MULTIPLE", false),
        })
    } else {
        None
    };

    let images = if extract_images {
        Some(ImageExtractionConfig {
            extract_images: true,
            target_dpi: parse_env_i32("KREUZBERG_IMAGE_TARGET_DPI", 300),
            max_image_dimension: parse_env_i32("KREUZBERG_IMAGE_MAX_DIMENSION", 4096),
            auto_adjust_dpi: parse_env_bool("KREUZBERG_IMAGE_AUTO_ADJUST_DPI", true),
            min_dpi: parse_env_i32("KREUZBERG_IMAGE_MIN_DPI", 72),
            max_dpi: parse_env_i32("KREUZBERG_IMAGE_MAX_DPI", 600),
        })
    } else {
        None
    };

    let pdf_passwords = env::var("KREUZBERG_PDF_PASSWORDS")
        .ok()
        .map(|value| {
            value
                .split(',')
                .map(|item| item.trim().to_string())
                .filter(|item| !item.is_empty())
                .collect::<Vec<_>>()
        })
        .filter(|items| !items.is_empty());

    let pdf_options = Some(PdfConfig {
        allow_single_column_tables: parse_env_bool("KREUZBERG_PDF_ALLOW_SINGLE_COLUMN_TABLES", false),
        extract_images: parse_env_bool("KREUZBERG_PDF_EXTRACT_IMAGES", false),
        extract_metadata: parse_env_bool("KREUZBERG_PDF_EXTRACT_METADATA", true),
        passwords: pdf_passwords,
        hierarchy: None,
    });

    ExtractionConfig {
        chunking: Some(ChunkingConfig {
            max_characters: parse_env_usize("KREUZBERG_CHUNK_MAX_CHARACTERS", 1200),
            overlap: parse_env_usize("KREUZBERG_CHUNK_OVERLAP", 150),
            chunker_type: ChunkerType::Markdown,
            ..Default::default()
        }),
        enable_quality_processing: parse_env_bool("KREUZBERG_ENABLE_QUALITY_PROCESSING", true),
        force_ocr,
        images,
        include_document_structure: parse_env_bool("KREUZBERG_INCLUDE_DOCUMENT_STRUCTURE", true),
        language_detection,
        max_concurrent_extractions: env::var("KREUZBERG_MAX_CONCURRENT_EXTRACTIONS")
            .ok()
            .and_then(|value| value.parse::<usize>().ok()),
        ocr,
        output_format: ContentOutputFormat::Markdown,
        pages: Some(PageConfig {
            extract_pages,
            insert_page_markers,
            marker_format: env::var("KREUZBERG_PAGE_MARKER_FORMAT")
                .unwrap_or_else(|_| "\n\n<!-- PAGE {page_num} -->\n\n".to_string()),
        }),
        pdf_options,
        use_cache: parse_env_bool("KREUZBERG_USE_CACHE", true),
        ..Default::default()
    }
}

#[derive(Clone)]
struct TableArtifact {
    table_index: usize,
    page_number: usize,
    headers: Vec<String>,
    cells: Vec<Vec<String>>,
    original_markdown: String,
    kv_markdown: String,
    row_chunks: Vec<String>,
    row_count: usize,
    column_count: usize,
}

fn build_table_artifacts(tables: &[Table], max_characters: usize) -> Vec<TableArtifact> {
    tables
        .iter()
        .enumerate()
        .map(|(table_index, table)| {
            let headers = derive_headers(table);
            let row_chunks = build_table_row_chunks(table, &headers, max_characters);
            let kv_markdown = build_table_kv_markdown(table, &headers, &row_chunks, table_index);
            let row_count = table.cells.len().saturating_sub(1);
            let column_count = headers.len();

            TableArtifact {
                table_index,
                page_number: table.page_number,
                headers,
                cells: table.cells.clone(),
                original_markdown: table.markdown.clone(),
                kv_markdown,
                row_chunks,
                row_count,
                column_count,
            }
        })
        .collect()
}

fn inject_table_kv_sections(content: &str, tables: &[TableArtifact]) -> String {
    let mut enriched = content.to_string();
    let mut replaced_any = false;

    for table in tables {
        if !table.original_markdown.trim().is_empty() && enriched.contains(&table.original_markdown) {
            enriched = enriched.replacen(&table.original_markdown, &table.kv_markdown, 1);
            replaced_any = true;
        }
    }

    if !replaced_any && !tables.is_empty() {
        enriched.push_str("\n\n# Extracted Tables\n");
        for table in tables {
            enriched.push_str("\n\n");
            enriched.push_str(&table.kv_markdown);
        }
    }

    enriched
}

fn derive_headers(table: &Table) -> Vec<String> {
    if let Some(first_row) = table.cells.first() {
        first_row
            .iter()
            .enumerate()
            .map(|(idx, header)| {
                let cleaned = normalize_cell(header);
                if cleaned.is_empty() {
                    format!("Column {}", idx + 1)
                } else {
                    cleaned
                }
            })
            .collect()
    } else {
        Vec::new()
    }
}

fn build_table_kv_markdown(
    table: &Table,
    headers: &[String],
    row_chunks: &[String],
    table_index: usize,
) -> String {
    let mut out = String::new();
    out.push_str(&format!(
        "## Table {} (Page {})\n\n",
        table_index + 1,
        table.page_number
    ));

    if !headers.is_empty() {
        out.push_str("### Columns\n");
        for header in headers {
            out.push_str(&format!("- {}\n", header));
        }
        out.push('\n');
    }

    if row_chunks.is_empty() {
        out.push_str("### Rows\n\nNo data rows extracted.\n");
    } else {
        for chunk in row_chunks {
            out.push_str(chunk);
            out.push_str("\n\n");
        }
    }

    out.trim().to_string()
}

fn build_table_row_chunks(table: &Table, headers: &[String], max_characters: usize) -> Vec<String> {
    let rows = if table.cells.len() > 1 {
        &table.cells[1..]
    } else {
        &[][..]
    };

    let mut sections = Vec::new();
    let mut buffer = String::new();
    let mut chunk_start_row = 1usize;
    let mut chunk_end_row = 0usize;

    for (idx, row) in rows.iter().enumerate() {
        let row_number = idx + 1;
        let row_blocks = render_row_blocks(headers, row, row_number, max_characters);

        for row_block in row_blocks {
            let candidate = if buffer.is_empty() {
                row_block.clone()
            } else {
                format!("{buffer}\n\n{row_block}")
            };

            if !buffer.is_empty() && candidate.chars().count() > max_characters {
                sections.push(wrap_table_row_section(chunk_start_row, chunk_end_row, &buffer));
                buffer = row_block;
                chunk_start_row = row_number;
                chunk_end_row = row_number;
            } else {
                buffer = candidate;
                chunk_end_row = row_number;
            }
        }
    }

    if !buffer.is_empty() {
        sections.push(wrap_table_row_section(chunk_start_row, chunk_end_row, &buffer));
    }

    sections
}

fn wrap_table_row_section(start_row: usize, end_row: usize, body: &str) -> String {
    if start_row == end_row {
        format!("### Row {}\n\n{}", start_row, body)
    } else {
        format!("### Rows {}-{}\n\n{}", start_row, end_row, body)
    }
}

fn render_row_blocks(
    headers: &[String],
    row: &[String],
    row_number: usize,
    max_characters: usize,
) -> Vec<String> {
    let mut blocks = Vec::new();
    let mut part_index = 1usize;
    let mut current = String::new();

    for (cell_index, cell) in row.iter().enumerate() {
        let header = headers
            .get(cell_index)
            .cloned()
            .unwrap_or_else(|| format!("Column {}", cell_index + 1));
        let entry = format!("- {}: {}", header, normalize_cell(cell));

        let candidate = if current.is_empty() {
            entry.clone()
        } else {
            format!("{current}\n{entry}")
        };

        let heading = if part_index == 1 {
            format!("#### Row {}", row_number)
        } else {
            format!("#### Row {} (Part {})", row_number, part_index)
        };

        if !current.is_empty() && (heading.len() + 2 + candidate.len()) > max_characters {
            blocks.push(format!("{heading}\n{current}"));
            current = entry;
            part_index += 1;
        } else {
            current = candidate;
        }
    }

    if !current.is_empty() {
        let heading = if part_index == 1 {
            format!("#### Row {}", row_number)
        } else {
            format!("#### Row {} (Part {})", row_number, part_index)
        };
        blocks.push(format!("{heading}\n{current}"));
    }

    if blocks.is_empty() {
        blocks.push(format!("#### Row {}\n- Value: ", row_number));
    }

    blocks
}

fn normalize_cell(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim()
        .to_string()
}

async fn upload_bytes(state: &AppState, key: String, body: Vec<u8>, content_type: &str) -> Result<String> {
    state
        .s3_client
        .put_object()
        .bucket(&state.bucket_name)
        .key(key.clone())
        .body(ByteStream::from(body))
        .content_type(content_type)
        .send()
        .await
        .with_context(|| format!("failed to upload {key}"))?;

    Ok(key)
}

fn publish_result(state: &AppState, queue_name: &str, result: &ExtractionResult) -> Result<()> {
    let mut conn = state.redis_client.get_connection()?;
    let payload = serde_json::to_string(result)?;
    let _: () = conn.rpush(queue_name, payload)?;
    info!(
        job_id = %result.job_id,
        queue = %queue_name,
        status = %result.status,
        "published extraction result"
    );
    Ok(())
}

fn checksum(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn safe_basename(name: &str) -> String {
    let sanitized = name
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect::<String>();
    if sanitized.is_empty() {
        "document".to_string()
    } else {
        sanitized
    }
}

fn env_var(name: &str) -> Result<String> {
    env::var(name).map_err(|_| anyhow!("missing required env var: {name}"))
}

fn parse_env_usize(name: &str, default: usize) -> usize {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(default)
}

fn parse_env_i32(name: &str, default: i32) -> i32 {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<i32>().ok())
        .unwrap_or(default)
}

fn parse_env_f64(name: &str, default: f64) -> f64 {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<f64>().ok())
        .unwrap_or(default)
}

fn parse_env_bool(name: &str, default: bool) -> bool {
    env::var(name)
        .ok()
        .map(|value| matches!(value.to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(default)
}
