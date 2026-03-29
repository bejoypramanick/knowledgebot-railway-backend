use anyhow::{anyhow, Context, Result};
use aws_config::BehaviorVersion;
use aws_credential_types::Credentials;
use aws_sdk_s3::{config::Region, primitives::ByteStream, Client as S3Client};
use chrono::Utc;
use kreuzberg::{
    detect_mime_type_from_bytes, extract_bytes, validate_mime_type, ChunkingConfig, ChunkerType,
    ExtractionConfig, ImageExtractionConfig, LanguageDetectionConfig, LayoutDetectionConfig,
    OcrConfig, OutputFormat as ContentOutputFormat, PageConfig, PdfConfig, Table,
    TesseractConfig,
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
    worker_type: String,
    s3_key: String,
    original_filename: Option<String>,
    mime_type: Option<String>,
    artifact_prefix: String,
    #[serde(default = "default_result_queue")]
    reply_channel: String,
}

#[derive(Debug, Serialize)]
struct ExtractionResult {
    job_id: String,
    document_id: String,
    worker_type: String,
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
    file_redis_client: Option<redis::Client>,
    web_redis_client: Option<redis::Client>,
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
    let task_queue = env::var("EXTRACT_TASK_QUEUE").unwrap_or_else(|_| DEFAULT_TASK_QUEUE.to_string());
    let bucket_name = env::var("RAILWAY_BUCKET_NAME")
        .or_else(|_| env::var("RAILWAY_VOLUME_NAME"))
        .unwrap_or_else(|_| "knowledgebot-storage".to_string());

    let endpoint_url = env_var("RAILWAY_STORAGE_URL")?;
    let access_key = env_var("RAILWAY_STORAGE_ACCESS_KEY")?;
    let secret_key = env_var("RAILWAY_STORAGE_SECRET_KEY")?;
    let region = env::var("RAILWAY_REGION").unwrap_or_else(|_| "us-east-1".to_string());

    let file_redis_client = env::var("FILE_REDIS_URL")
        .ok()
        .map(|url| redis::Client::open(url.clone()).with_context(|| format!("invalid FILE_REDIS_URL: {url}")))
        .transpose()?;
    let web_redis_client = env::var("WEB_REDIS_URL")
        .ok()
        .map(|url| redis::Client::open(url.clone()).with_context(|| format!("invalid WEB_REDIS_URL: {url}")))
        .transpose()?;

    if file_redis_client.is_none() && web_redis_client.is_none() {
        return Err(anyhow!("missing FILE_REDIS_URL and WEB_REDIS_URL"));
    }

    let creds = Credentials::new(access_key, secret_key, None, None, "railway-storage");
    let shared_config = aws_config::defaults(BehaviorVersion::latest())
        .region(Region::new(region.clone()))
        .credentials_provider(creds)
        .load()
        .await;

    let s3_config = aws_sdk_s3::config::Builder::from(&shared_config)
        .endpoint_url(endpoint_url.clone())
        .force_path_style(true)
        .build();

    let s3_client = S3Client::from_conf(s3_config);
    let http_client = HttpClient::builder()
        .timeout(Duration::from_secs(300))
        .build()
        .context("failed to build http client")?;

    info!(
        bucket = %bucket_name,
        endpoint = %endpoint_url,
        region = %region,
        file_redis = %file_redis_client.is_some(),
        web_redis = %web_redis_client.is_some(),
        "kreuzberg-worker storage/runtime configured"
    );

    Ok(AppState {
        file_redis_client,
        web_redis_client,
        s3_client,
        http_client,
        bucket_name,
        task_queue,
    })
}

fn pop_job(state: &AppState) -> Result<Option<ExtractionJob>> {
    if let Some(job) = pop_job_from_client(state.file_redis_client.as_ref(), &state.task_queue, "file")? {
        return Ok(Some(job));
    }
    if let Some(job) = pop_job_from_client(state.web_redis_client.as_ref(), &state.task_queue, "web")? {
        return Ok(Some(job));
    }
    Ok(None)
}

fn pop_job_from_client(
    client: Option<&redis::Client>,
    task_queue: &str,
    worker_type: &str,
) -> Result<Option<ExtractionJob>> {
    let Some(client) = client else {
        return Ok(None);
    };
    let mut conn = client.get_connection()?;
    let result: Option<(String, String)> = redis::cmd("BLPOP").arg(task_queue).arg(1).query(&mut conn)?;
    if let Some((_queue, payload)) = result {
        let job: ExtractionJob = serde_json::from_str(&payload).context("invalid extraction payload")?;
        info!(job_id = %job.job_id, document_id = %job.document_id, worker_type = %worker_type, "received extraction job");
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
                worker_type: job.worker_type.clone(),
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
    info!(
        job_id = %job.job_id,
        document_id = %job.document_id,
        worker_type = %job.worker_type,
        bucket = %state.bucket_name,
        s3_key = %job.s3_key,
        "starting S3-backed extraction job"
    );
    let file_bytes = download_from_s3(state, &job.s3_key).await?;
    let extraction = extract_and_chunk(job, &file_bytes).await?;

    if extraction.markdown.trim().is_empty() {
        return Err(anyhow!(
            "extraction produced empty markdown (mime_type may be unsupported or content extraction failed)"
        ));
    }

    let markdown_key = upload_bytes(
        state,
        format!("{}.md", job.artifact_prefix),
        extraction.markdown.as_bytes().to_vec(),
        "text/markdown; charset=utf-8",
    )
    .await?;

    let chunks_key = upload_bytes(
        state,
        format!("{}_chunks.json", job.artifact_prefix),
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
                format!("{}_tables.json", job.artifact_prefix),
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
        format!("{}_manifest.json", job.artifact_prefix),
        serde_json::to_vec_pretty(&manifest)?,
        "application/json",
    )
    .await?;

    Ok(ExtractionResult {
        job_id: job.job_id.clone(),
        document_id: job.document_id.clone(),
        worker_type: job.worker_type.clone(),
        status: "completed".to_string(),
        manifest_s3_key: Some(manifest_key),
        error: None,
        completed_at: Utc::now().to_rfc3339(),
    })
}

async fn download_from_s3(state: &AppState, s3_key: &str) -> Result<Vec<u8>> {
    info!(bucket = %state.bucket_name, s3_key = %s3_key, "checking source object before download");
    state
        .s3_client
        .head_object()
        .bucket(&state.bucket_name)
        .key(s3_key)
        .send()
        .await
        .with_context(|| format!("failed head_object for S3 key: {s3_key}"))?;

    info!(bucket = %state.bucket_name, s3_key = %s3_key, "downloading source object from S3");
    let response = state
        .s3_client
        .get_object()
        .bucket(&state.bucket_name)
        .key(s3_key)
        .send()
        .await
        .with_context(|| format!("failed to download object from S3: {s3_key}"))?;

    let body = response
        .body
        .collect()
        .await
        .context("failed to read S3 response body")?;
    Ok(body.into_bytes().to_vec())
}

struct ExtractionArtifacts {
    markdown: String,
    chunks: Vec<ExtractedChunk>,
    tables: serde_json::Value,
    metadata: serde_json::Value,
}

async fn extract_and_chunk(job: &ExtractionJob, file_bytes: &[u8]) -> Result<ExtractionArtifacts> {
    let checksum = checksum(file_bytes);
    let mime_type = resolve_mime_type(job, file_bytes)
        .context("unable to validate or detect mime type for extraction")?;
    info!(
        job_id = %job.job_id,
        document_id = %job.document_id,
        worker_type = %job.worker_type,
        mime_type = %mime_type,
        bytes = file_bytes.len(),
        "running kreuzberg extract_bytes"
    );
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

    info!(
        job_id = %job.job_id,
        document_id = %job.document_id,
        content_chars = result.content.chars().count(),
        tables = result.tables.len(),
        has_chunks = result.chunks.as_ref().map(|c| c.len()).unwrap_or(0),
        "kreuzberg extraction completed"
    );

    let enriched_tables = build_table_artifacts(&result.tables, chunk_size);
    let markdown = strip_table_markdown_sections(&result.content, &enriched_tables);
    info!(
        job_id = %job.job_id,
        document_id = %job.document_id,
        markdown_chars = markdown.chars().count(),
        "prepared markdown artifacts"
    );
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

    let mut chunks = chunked_markdown
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

    // Use dedicated row-group table chunks for retrieval instead of also rewriting tables into
    // the main markdown stream. This keeps RAG recall strong while avoiding duplicate table hits.
    let base_chunk_index = chunks.len();
    let mut next_chunk_index = base_chunk_index;
    for table in &enriched_tables {
        for row_chunk in &table.row_chunks {
            chunks.push(ExtractedChunk {
                text: row_chunk.text.clone(),
                metadata: json!({
                    "chunk_index": next_chunk_index,
                    "strategy": "kreuzberg_table_rows",
                    "table_index": table.table_index,
                    "table_page_number": table.page_number,
                    "row_start": row_chunk.start_row,
                    "row_end": row_chunk.end_row,
                    "headers": table.headers,
                }),
            });
            next_chunk_index += 1;
        }
    }

    let tables = serde_json::Value::Array(
        enriched_tables
            .iter()
            .map(|table| {
                json!({
                    "table_index": table.table_index,
                    "page_number": table.page_number,
                    "markdown": table.original_markdown,
                    "kv_markdown": table.kv_markdown,
                    "row_chunks": table
                        .row_chunks
                        .iter()
                        .map(|chunk| json!({
                            "row_start": chunk.start_row,
                            "row_end": chunk.end_row,
                            "text": chunk.text,
                        }))
                        .collect::<Vec<_>>(),
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
        "table_kv_enabled": false,
        "table_aware_chunking_enabled": false,
        "table_row_chunks_enabled": true,
    });

    Ok(ExtractionArtifacts { markdown, chunks, tables, metadata })
}

fn resolve_mime_type(job: &ExtractionJob, file_bytes: &[u8]) -> Result<String> {
    if let Some(mime_type) = job.mime_type.as_deref() {
        if let Ok(validated) = validate_mime_type(mime_type) {
            return Ok(validated.to_string());
        }
    }

    if let Some(filename) = job.original_filename.as_deref().or(Some(job.s3_key.as_str())) {
        let lowered = filename.to_ascii_lowercase();
        let inferred = if lowered.ends_with(".html") || lowered.ends_with(".htm") {
            Some("text/html")
        } else if lowered.ends_with(".md") || lowered.ends_with(".markdown") {
            Some("text/markdown")
        } else if lowered.ends_with(".pdf") {
            Some("application/pdf")
        } else if lowered.ends_with(".docx") {
            Some("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        } else if lowered.ends_with(".pptx") {
            Some("application/vnd.openxmlformats-officedocument.presentationml.presentation")
        } else if lowered.ends_with(".xlsx") {
            Some("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        } else if lowered.ends_with(".csv") {
            Some("text/csv")
        } else {
            None
        };

        if let Some(mime_type) = inferred {
            if let Ok(validated) = validate_mime_type(mime_type) {
                return Ok(validated.to_string());
            }
        }
    }

    Ok(
        detect_mime_type_from_bytes(file_bytes)
            .or_else(|_| validate_mime_type("application/octet-stream"))
            .map(|mime| mime.to_string())?,
    )
}

fn build_extraction_config() -> ExtractionConfig {
    let ocr_enabled = parse_env_bool("KREUZBERG_OCR_ENABLED", false);
    let force_ocr = parse_env_bool("KREUZBERG_FORCE_OCR", false);
    let detect_languages = parse_env_bool("KREUZBERG_LANGUAGE_DETECTION_ENABLED", false);
    let extract_images = parse_env_bool("KREUZBERG_IMAGE_EXTRACTION_ENABLED", false);
    let enable_layout_detection = parse_env_bool("KREUZBERG_LAYOUT_DETECTION_ENABLED", true);
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
            inject_placeholders: parse_env_bool("KREUZBERG_IMAGE_INJECT_PLACEHOLDERS", false),
            target_dpi: parse_env_i32("KREUZBERG_IMAGE_TARGET_DPI", 300),
            max_image_dimension: parse_env_i32("KREUZBERG_IMAGE_MAX_DIMENSION", 4096),
            auto_adjust_dpi: parse_env_bool("KREUZBERG_IMAGE_AUTO_ADJUST_DPI", true),
            min_dpi: parse_env_i32("KREUZBERG_IMAGE_MIN_DPI", 72),
            max_dpi: parse_env_i32("KREUZBERG_IMAGE_MAX_DPI", 600),
        })
    } else {
        None
    };

    let layout = if enable_layout_detection {
        Some(LayoutDetectionConfig {
            preset: env::var("KREUZBERG_LAYOUT_DETECTION_PRESET")
                .unwrap_or_else(|_| "fast".to_string()),
            table_model: env::var("KREUZBERG_LAYOUT_DETECTION_TABLE_MODEL")
                .unwrap_or_else(|_| "slanet".to_string()),
            confidence_threshold: env::var("KREUZBERG_LAYOUT_DETECTION_CONFIDENCE_THRESHOLD")
                .ok()
                .and_then(|value| value.parse::<f32>().ok()),
            apply_heuristics: parse_env_bool("KREUZBERG_LAYOUT_DETECTION_APPLY_HEURISTICS", true),
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
        extract_annotations: parse_env_bool("KREUZBERG_PDF_EXTRACT_ANNOTATIONS", false),
        extract_images: parse_env_bool("KREUZBERG_PDF_EXTRACT_IMAGES", false),
        extract_metadata: parse_env_bool("KREUZBERG_PDF_EXTRACT_METADATA", true),
        top_margin_fraction: Some(parse_env_f32("KREUZBERG_PDF_TOP_MARGIN_FRACTION", 0.0)),
        bottom_margin_fraction: Some(parse_env_f32("KREUZBERG_PDF_BOTTOM_MARGIN_FRACTION", 0.0)),
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
        layout,
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
    row_chunks: Vec<TableRowChunk>,
    row_count: usize,
    column_count: usize,
}

#[derive(Clone)]
struct TableRowChunk {
    start_row: usize,
    end_row: usize,
    text: String,
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

fn strip_table_markdown_sections(content: &str, tables: &[TableArtifact]) -> String {
    let mut stripped = content.to_string();

    for table in tables {
        let table_markdown = table.original_markdown.trim();
        if table_markdown.is_empty() {
            continue;
        }

        if stripped.contains(table_markdown) {
            stripped = stripped.replacen(table_markdown, "", 1);
        }
    }

    normalize_spacing_after_table_removal(&stripped)
}

fn normalize_spacing_after_table_removal(content: &str) -> String {
    let mut normalized = String::new();
    let mut blank_line_count = 0usize;

    for line in content.lines() {
        let is_blank = line.trim().is_empty();
        if is_blank {
            blank_line_count += 1;
            if blank_line_count > 2 {
                continue;
            }
            normalized.push('\n');
        } else {
            blank_line_count = 0;
            normalized.push_str(line.trim_end());
            normalized.push('\n');
        }
    }

    normalized.trim().to_string()
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
    row_chunks: &[TableRowChunk],
    table_index: usize,
) -> String {
    let mut out = String::new();
    let table_heading = derive_table_heading(&table.markdown);
    out.push_str(&format!(
        "## Table {} (Page {})\n\n",
        table_index + 1,
        table.page_number
    ));

    if let Some(heading) = table_heading.as_deref() {
        out.push_str(&format!("### {}\n\n", heading));
    }

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
            out.push_str(&chunk.text);
            out.push_str("\n\n");
        }
    }

    out.trim().to_string()
}

fn build_table_row_chunks(table: &Table, headers: &[String], max_characters: usize) -> Vec<TableRowChunk> {
    let table_heading = derive_table_heading(&table.markdown);
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
        let row_blocks = render_row_blocks(
            table_heading.as_deref(),
            headers,
            row,
            row_number,
            max_characters,
        );

        for row_block in row_blocks {
            let candidate = if buffer.is_empty() {
                row_block.clone()
            } else {
                format!("{buffer}\n\n{row_block}")
            };

            if !buffer.is_empty() && candidate.chars().count() > max_characters {
                sections.push(wrap_table_row_section(
                    table_heading.as_deref(),
                    headers,
                    chunk_start_row,
                    chunk_end_row,
                    &buffer,
                ));
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
        sections.push(wrap_table_row_section(
            table_heading.as_deref(),
            headers,
            chunk_start_row,
            chunk_end_row,
            &buffer,
        ));
    }

    sections
}

fn wrap_table_row_section(
    table_heading: Option<&str>,
    headers: &[String],
    start_row: usize,
    end_row: usize,
    body: &str,
) -> TableRowChunk {
    let heading = if start_row == end_row {
        format!("### Row {}", start_row)
    } else {
        format!("### Rows {}-{}", start_row, end_row)
    };

    // Replicate headers into every row-chunk so retrieval has column names.
    let columns_line = if headers.is_empty() {
        String::new()
    } else {
        format!("Columns: {}", headers.join(" | "))
    };

    let mut text = String::new();
    text.push_str(&heading);
    text.push_str("\n\n");
    if let Some(table_heading) = table_heading {
        text.push_str(table_heading);
        text.push_str("\n\n");
    }
    if !columns_line.is_empty() {
        text.push_str(&columns_line);
        text.push_str("\n\n");
    }
    text.push_str(body);

    TableRowChunk {
        start_row,
        end_row,
        text,
    }
}

fn derive_table_heading(markdown: &str) -> Option<String> {
    markdown
        .lines()
        .map(str::trim)
        .find(|line| {
            !line.is_empty()
                && !line.starts_with('|')
                && !line.starts_with(":-")
                && !line.starts_with("---")
        })
        .map(normalize_cell)
        .filter(|line| !line.is_empty())
}

fn render_row_blocks(
    table_heading: Option<&str>,
    headers: &[String],
    row: &[String],
    row_number: usize,
    max_characters: usize,
) -> Vec<String> {
    let mut blocks = Vec::new();
    let mut part_index = 1usize;
    let mut current = String::new();
    let row_summary = build_row_summary(table_heading, headers, row, row_number);

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
        let prefix = if part_index == 1 && !row_summary.is_empty() {
            format!("{row_summary}\n")
        } else {
            String::new()
        };

        if !current.is_empty() && (heading.len() + 1 + prefix.len() + candidate.len()) > max_characters {
            blocks.push(format!("{heading}\n{prefix}{current}"));
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
        let prefix = if part_index == 1 && !row_summary.is_empty() {
            format!("{row_summary}\n")
        } else {
            String::new()
        };
        blocks.push(format!("{heading}\n{prefix}{current}"));
    }

    if blocks.is_empty() {
        let prefix = if !row_summary.is_empty() {
            format!("{row_summary}\n")
        } else {
            String::new()
        };
        blocks.push(format!("#### Row {}\n{}- Value: ", row_number, prefix));
    }

    blocks
}

fn build_row_summary(
    table_heading: Option<&str>,
    headers: &[String],
    row: &[String],
    row_number: usize,
) -> String {
    let parts = row
        .iter()
        .enumerate()
        .filter_map(|(cell_index, cell)| {
            let normalized = normalize_cell(cell);
            if normalized.is_empty() {
                return None;
            }
            let header = headers
                .get(cell_index)
                .cloned()
                .unwrap_or_else(|| format!("Column {}", cell_index + 1));
            Some(format!("{} {}", header, normalized))
        })
        .collect::<Vec<_>>();

    if parts.is_empty() {
        String::new()
    } else {
        let mut summary_parts = Vec::new();
        if let Some(table_heading) = table_heading {
            if !table_heading.trim().is_empty() {
                summary_parts.push(table_heading.trim().to_string());
            }
        }
        summary_parts.push(format!("Row {}", row_number));
        summary_parts.extend(parts);
        summary_parts.join(" | ")
    }
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
    let client = if result.worker_type == "web" {
        state.web_redis_client.as_ref()
    } else {
        state.file_redis_client.as_ref()
    }
    .ok_or_else(|| anyhow!("missing redis client for worker_type {}", result.worker_type))?;
    let mut conn = client.get_connection()?;
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

fn parse_env_f32(name: &str, default: f32) -> f32 {
    env::var(name)
        .ok()
        .and_then(|value| value.parse::<f32>().ok())
        .unwrap_or(default)
}

fn parse_env_bool(name: &str, default: bool) -> bool {
    env::var(name)
        .ok()
        .map(|value| matches!(value.to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(default)
}
