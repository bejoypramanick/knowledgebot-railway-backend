"""
Usage Report - Single Endpoint
GET /reports/usage → self-contained HTML report.
All filtering and Excel download handled client-side.
Protected by session auth middleware.
"""

import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from sqlalchemy import text

logger = get_otel_logger("usage_report", "api-gateway")
router = APIRouter(prefix="/reports", tags=["reports"])


def _row_to_dict(row):
    """Convert a SQLAlchemy row to a JSON-safe dict."""
    d = dict(row._mapping)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, (dict, list)):
            continue  # Preserve JSONB structures
        elif hasattr(v, "__str__") and not isinstance(
            v, (int, float, bool, str, type(None))
        ):
            d[k] = str(v)
    return d


def _chunk_stats_to_dict(row):
    """Convert a chunk stats row to JSON-safe dict with string keys."""
    d = dict(row._mapping)
    # Convert document_id (UUID) to string for JSON
    if "document_id" in d and d["document_id"]:
        d["document_id"] = str(d["document_id"])
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif hasattr(v, "__str__") and not isinstance(
            v, (int, float, bool, str, type(None))
        ):
            d[k] = str(v)
    return d


async def _fetch_all_data(tenant_id: str = None):
    """Fetch report data, retrying once if asyncpg has a stale prepared plan."""
    try:
        return await _fetch_all_data_once(tenant_id=tenant_id)
    except Exception as exc:
        if not _is_stale_prepared_statement_error(exc):
            raise

        logger.warning(
            "Usage report hit a stale asyncpg prepared statement after a DB schema "
            "change; retrying once with a fresh session."
        )
        return await _fetch_all_data_once(tenant_id=tenant_id)


def _is_stale_prepared_statement_error(exc: Exception) -> bool:
    """Detect asyncpg cached-plan failures raised through SQLAlchemy wrappers."""
    error_text = str(exc)
    return (
        "InvalidCachedStatementError" in error_text
        or "cached statement plan is invalid" in error_text
        or "cached plan must not change result type" in error_text
    )


async def _fetch_all_data_once(tenant_id: str = None):
    """Fetch 365 days of data. If tenant_id provided, filter by tenant."""
    from uuid import UUID

    since = datetime.utcnow() - timedelta(days=365)
    tenant_uuid = UUID(tenant_id) if tenant_id else None

    async with get_db_session() as db:
        tenants = {
            str(r.id): {"id": str(r.id), "name": r.name, "slug": r.slug}
            for r in (
                await db.execute(text("SELECT id, name, slug FROM tenants"))
            ).fetchall()
        }

        # Use RLS-bypassing functions
        params = {"p_tenant_id": tenant_uuid, "p_since": since}
        direct_params = {"tenant_id": tenant_uuid, "since": since}
        sessions = [
            _row_to_dict(r)
            for r in (
                await db.execute(
                    text("SELECT * FROM get_usage_sessions(:p_tenant_id, :p_since)"),
                    params,
                )
            ).fetchall()
        ]

        files = [
            _row_to_dict(r)
            for r in (
                await db.execute(
                    text("SELECT * FROM get_usage_files(:p_tenant_id, :p_since)"),
                    params,
                )
            ).fetchall()
        ]

        # Get chunk stats for files
        file_chunk_stats = {
            str(r.document_id): _chunk_stats_to_dict(r)
            for r in (
                await db.execute(
                    text("""
            SELECT document_id,
                   COUNT(*) as chunk_count,
                   SUM(pg_column_size(content))::bigint as content_storage_bytes,
                   SUM(pg_column_size(embedding))::bigint as embedding_storage_bytes,
                   pg_size_pretty(CAST(SUM(pg_column_size(content)) AS bigint)) as content_pretty,
                   pg_size_pretty(CAST(SUM(pg_column_size(embedding)) AS bigint)) as embedding_pretty
            FROM document_chunks
            WHERE document_type = 'file'
              AND (CAST(:tenant_id AS UUID) IS NULL OR tenant_id = CAST(:tenant_id AS UUID))
              AND document_id IN (
                SELECT id
                FROM file_uploads
                WHERE created_at >= :since
                  AND (CAST(:tenant_id AS UUID) IS NULL OR tenant_id = CAST(:tenant_id AS UUID))
              )
            GROUP BY document_id
        """),
                    direct_params,
                )
            ).fetchall()
        }

        # Use RLS-bypassing function for websites
        websites = [
            _row_to_dict(r)
            for r in (
                await db.execute(
                    text("SELECT * FROM get_usage_websites(:p_tenant_id, :p_since)"),
                    params,
                )
            ).fetchall()
        ]

        # Get chunk stats for websites
        website_chunk_stats = {
            str(r.document_id): _chunk_stats_to_dict(r)
            for r in (
                await db.execute(
                    text("""
            SELECT document_id,
                   COUNT(*) as chunk_count,
                   SUM(pg_column_size(content))::bigint as content_storage_bytes,
                   SUM(pg_column_size(embedding))::bigint as embedding_storage_bytes,
                   pg_size_pretty(CAST(SUM(pg_column_size(content)) AS bigint)) as content_pretty,
                   pg_size_pretty(CAST(SUM(pg_column_size(embedding)) AS bigint)) as embedding_pretty
            FROM document_chunks
            WHERE document_type = 'website'
              AND (CAST(:tenant_id AS UUID) IS NULL OR tenant_id = CAST(:tenant_id AS UUID))
              AND document_id IN (
                SELECT id
                FROM scraped_websites
                WHERE created_at >= :since
                  AND (CAST(:tenant_id AS UUID) IS NULL OR tenant_id = CAST(:tenant_id AS UUID))
              )
            GROUP BY document_id
        """),
                    direct_params,
                )
            ).fetchall()
        }

        chat_messages = [
            _row_to_dict(r)
            for r in (
                await db.execute(
                    text("""
            SELECT cm.id, cm.session_id, cm.role, cm.content,
                   cm.character_count, cm.word_count, cm.token_count,
                   cm.message_token_count, cm.prompt_token_count, cm.completion_token_count,
                   cm.system_prompt_char_count, cm.system_prompt_word_count, cm.system_prompt_token_count,
                   cm.history_char_count, cm.history_word_count, cm.history_token_count,
                   cm.tool_def_char_count, cm.tool_def_word_count, cm.tool_def_token_count,
                   cm.user_msg_char_count, cm.user_msg_word_count, cm.user_msg_token_count,
                   cm.bot_response_char_count, cm.bot_response_word_count, cm.bot_response_token_count,
                   cm.system_prompt_text, cm.history_text, cm.tool_def_text,
                   cm.created_at
            FROM chat_messages cm
            WHERE cm.created_at >= :since
              AND (CAST(:tenant_id AS UUID) IS NULL OR cm.tenant_id = CAST(:tenant_id AS UUID))
            ORDER BY cm.created_at DESC
        """),
                    direct_params,
                )
            ).fetchall()
        ]

        run_steps = [
            _row_to_dict(r)
            for r in (
                await db.execute(
                    text("""
            SELECT id, session_id, user_message_id, step_number, step_type, part_type,
                   tool_name, content_preview, content_full, char_count, word_count,
                   token_count, token_source, created_at
            FROM agent_run_steps
            WHERE created_at >= :since
              AND (CAST(:tenant_id AS UUID) IS NULL OR tenant_id = CAST(:tenant_id AS UUID))
            ORDER BY session_id, user_message_id, step_number
        """),
                    direct_params,
                )
            ).fetchall()
        ]

        token_usage_log = []
        rows = (
            await db.execute(
                text("""
            SELECT tul.id, tul.session_id, tul.message_id, tul.provider, tul.model,
                   tul.prompt_tokens, tul.completion_tokens, tul.total_tokens,
                   tul.api_call_type, tul.request_metadata, tul.created_at
            FROM token_usage_log tul
            WHERE tul.created_at >= :since
              AND (CAST(:tenant_id AS UUID) IS NULL OR tul.tenant_id = CAST(:tenant_id AS UUID))
            ORDER BY tul.created_at DESC
        """),
                direct_params,
            )
        ).fetchall()

        for r in rows:
            d = _row_to_dict(r)
            meta = d.get("request_metadata")
            if meta and isinstance(meta, str):
                try:
                    # Fallback if DB driver returned a string for JSONB
                    d["request_metadata"] = json.loads(meta)
                    logger.debug(f"Parsed metadata string for row {d['id']}")
                except:
                    pass
            token_usage_log.append(d)

    logger.info(f"Report data fetched: {len(token_usage_log)} usage rows")
    if token_usage_log:
        first_meta = token_usage_log[0].get("request_metadata")
        logger.info(
            f"Sample metadata type: {type(first_meta)} value: {str(first_meta)[:100]}"
        )

    logger.info(
        f"Fetched {len(sessions)} sessions, {len(files)} files, {len(websites)} websites, {len(tenants)} tenants"
    )
    return {
        "tenants": tenants,
        "sessions": sessions,
        "files": files,
        "websites": websites,
        "chat_messages": chat_messages,
        "run_steps": run_steps,
        "token_usage_log": token_usage_log,
        "file_chunk_stats": file_chunk_stats,
        "website_chunk_stats": website_chunk_stats,
    }


@router.get("/usage/chunks")
async def usage_report_chunks(
    request: Request,
    document_id: str = Query(...),
    document_type: str = Query(...),
    tenant: str = Query(default=""),
):
    if document_type not in {"file", "website"}:
        raise HTTPException(status_code=400, detail="document_type must be 'file' or 'website'")

    from uuid import UUID

    tenant_uuid = UUID(tenant) if tenant else None
    document_uuid = UUID(document_id)

    async with get_db_session() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT
                        id,
                        document_id,
                        document_type,
                        chunk_index,
                        ROW_NUMBER() OVER (ORDER BY chunk_index ASC, created_at ASC) AS chunk_row_number,
                        content,
                        metadata,
                        COALESCE(metadata->>'url', '') AS page_url,
                        COALESCE(metadata->>'title', '') AS page_title,
                        char_length(content) AS char_count,
                        CASE
                            WHEN btrim(content) = '' THEN 0
                            ELSE cardinality(regexp_split_to_array(btrim(content), '[[:space:]]+'))
                        END AS word_count,
                        octet_length(content) AS size_bytes,
                        pg_column_size(content) AS content_storage_bytes,
                        pg_column_size(embedding) AS embedding_storage_bytes,
                        pg_size_pretty(CAST(pg_column_size(content) AS bigint)) AS content_pretty,
                        pg_size_pretty(CAST(pg_column_size(embedding) AS bigint)) AS embedding_pretty,
                        created_at
                    FROM document_chunks
                    WHERE document_id = :document_id
                      AND document_type = :document_type
                      AND (
                        CAST(:tenant_id AS UUID) IS NULL
                        OR tenant_id = CAST(:tenant_id AS UUID)
                      )
                    ORDER BY chunk_index ASC, created_at ASC
                    """
                ),
                {
                    "document_id": document_uuid,
                    "document_type": document_type,
                    "tenant_id": tenant_uuid,
                },
            )
        ).fetchall()

    return JSONResponse(
        content={
            "success": True,
            "chunks": [_row_to_dict(row) for row in rows],
        }
    )


@router.get("/usage", response_class=HTMLResponse)
async def usage_report(request: Request, tenant: str = ""):
    """Single endpoint. Filter by tenant on server-side via ?tenant= query param."""
    print(f"[USAGE REPORT] tenant param: '{tenant}'")
    data = await _fetch_all_data(tenant_id=tenant if tenant else None)
    print(
        f"[USAGE REPORT] returned {len(data.get('sessions', []))} sessions, {len(data.get('files', []))} files"
    )
    data_json = json.dumps(data, default=str).replace("</", "<\\/")

    html = (
        """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Usage Report</title>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<style>
:root {
  --bg:#ffffff;--card:#f8f9fa;--border:#dee2e6;--text:#212529;
  --muted:#6c757d;--accent:#4f46e5;--accent2:#7c3aed;--green:#16a34a;
  --orange:#ea580c;--red:#dc2626;--blue:#2563eb;--cyan:#0891b2;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);padding:24px}
.container{max-width:1400px;margin:0 auto}
h1{font-size:28px;margin-bottom:4px}
.subtitle{color:var(--muted);margin-bottom:24px;font-size:14px}
.toolbar{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap;align-items:center}
.toolbar button,.toolbar select{padding:8px 16px;border-radius:8px;font-size:13px;cursor:pointer;border:1px solid var(--border);background:var(--card);color:var(--text);transition:.2s}
.toolbar button:hover{border-color:var(--accent);background:rgba(79,70,229,.08)}
.toolbar .active{border-color:var(--accent);background:rgba(79,70,229,.12);color:var(--accent)}
.summary-actions{display:flex;gap:10px;flex-wrap:wrap;margin:-8px 0 24px}
.summary-actions button{padding:10px 16px;border-radius:8px;border:1px solid var(--border);background:var(--text);color:#fff;font-size:13px;cursor:pointer}
.summary-actions button.secondary{background:var(--card);color:var(--text)}
.summary-actions button:hover{opacity:.88}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:32px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.kpi .label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.kpi .value{font-size:28px;font-weight:700}
.kpi .sub{font-size:12px;color:var(--muted);margin-top:4px}
.accent{color:var(--accent)}.green{color:var(--green)}.orange{color:var(--orange)}.cyan{color:var(--cyan)}.red{color:var(--red)}
.section{margin-bottom:32px}
.section h2{font-size:20px;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:10px 12px;background:var(--card);border-bottom:2px solid var(--border);color:var(--muted);font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:.5px;position:sticky;top:0}
td{padding:10px 12px;border-bottom:1px solid var(--border)}
tr:hover td{background:rgba(79,70,229,.04)}
.mono{font-family:'SF Mono','Fira Code',monospace;font-size:12px}
.token-cell{font-weight:600;color:var(--accent)}
.badge{padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600}
.badge-active,.badge-completed{background:rgba(34,197,94,.15);color:var(--green)}
.badge-closed,.badge-archived{background:rgba(156,163,175,.15);color:var(--muted)}
.badge-processing,.badge-pending{background:rgba(249,115,22,.15);color:var(--orange)}
.badge-failed,.badge-cancelled,.badge-deleted{background:rgba(239,68,68,.15);color:var(--red)}
.badge-user{background:rgba(99,102,241,.15);color:var(--accent)}
.badge-assistant{background:rgba(34,197,94,.15);color:var(--green)}
.badge-human_agent{background:rgba(249,115,22,.15);color:var(--orange)}
.session-row{cursor:pointer;transition:.15s}
.session-row:hover td{background:rgba(79,70,229,.06)}
.session-row td:first-child::before{content:'\\25B6';margin-right:8px;font-size:10px;color:var(--muted);transition:.2s;display:inline-block}
.session-row.open td:first-child::before{transform:rotate(90deg)}
.msg-row{background:rgba(79,70,229,.02)}
.msg-row td{padding:8px 12px 8px 32px;font-size:12px;border-bottom:1px solid var(--border)}
.msg-bubble{white-space:pre-wrap;word-break:break-word;line-height:1.5;max-width:600px;cursor:pointer}
.msg-bubble.msg-collapsed{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:500px;max-height:1.5em}
.msg-row-header td{padding:6px 12px 6px 32px;font-size:11px;color:var(--muted);background:rgba(79,70,229,.06);font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.bd-table{width:100%;border-collapse:collapse;font-size:11px;margin:4px 0}
.bd-table th{text-align:left;padding:4px 8px;background:rgba(79,70,229,.08);color:var(--muted);font-weight:600;font-size:10px;text-transform:uppercase;letter-spacing:.3px;border:1px solid var(--border)}
.bd-table td{padding:4px 8px;border:1px solid var(--border);vertical-align:top}
.bd-table .bd-label{font-weight:600;color:var(--accent);white-space:nowrap;width:120px}
.bd-table .bd-num{text-align:right;font-weight:600;color:var(--accent);white-space:nowrap;width:70px}
.bd-table .bd-text{max-width:500px}
.bd-text-preview{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:500px;max-height:1.4em;cursor:pointer;color:var(--muted);font-size:11px}
.bd-text-preview.expanded{white-space:pre-wrap;max-width:500px;max-height:none;overflow:visible}
.loading{text-align:center;padding:40px;color:var(--muted)}
.table-wrap{overflow-x:auto;max-height:500px;overflow-y:auto;border:1px solid var(--border);border-radius:8px}
th[title]{cursor:help;border-bottom:2px dashed var(--border)}
.th-with-info{display:inline-flex;align-items:center;gap:6px}
.info-icon{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;border-radius:999px;border:1px solid var(--accent);background:#fff;color:var(--accent);font-size:10px;font-weight:700;line-height:1;cursor:pointer;padding:0;flex-shrink:0}
.info-icon:hover,.info-icon[aria-expanded="true"]{background:var(--accent);color:#fff}
.header-tooltip-popover{position:fixed;display:none;max-width:320px;min-width:260px;background:#fff;border:1px solid var(--border);border-radius:10px;box-shadow:0 14px 32px rgba(15,23,42,.18);padding:12px 14px;z-index:9999}
.header-tooltip-title{font-size:12px;font-weight:700;color:var(--text);margin-bottom:6px}
.header-tooltip-body{font-size:12px;line-height:1.55;color:var(--text);white-space:pre-line;text-transform:none;letter-spacing:0}
.text-popup-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;align-items:center;justify-content:center;padding:24px;z-index:10000}
.text-popup{width:min(900px,100%);max-height:min(80vh,900px);background:#fff;border:1px solid var(--border);border-radius:12px;box-shadow:0 20px 45px rgba(15,23,42,.22);display:flex;flex-direction:column;overflow:hidden}
.text-popup-header{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--border);gap:12px}
.text-popup-title{font-size:14px;font-weight:700;color:var(--text)}
.text-popup-close{border:1px solid var(--border);background:#fff;border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer}
.text-popup-body{padding:16px;overflow:auto}
.text-popup-pre{white-space:pre-wrap;word-break:break-word;font-family:'SF Mono','Fira Code',monospace;font-size:12px;line-height:1.6;color:var(--text)}
.number-link{background:none;border:none;padding:0;margin:0;color:var(--accent);font:inherit;font-weight:700;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.number-link:disabled{color:var(--muted);cursor:default;text-decoration:none}
.token-summary{background:linear-gradient(135deg,#f0f9ff,#eef2ff);border:1px solid #bfdbfe;border-radius:12px;padding:20px;margin-bottom:32px}
.token-summary h2{font-size:20px;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #bfdbfe;color:#1d4ed8}
.token-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.token-item{background:#fff;border:1px solid #dbeafe;border-radius:8px;padding:16px}
.token-item .token-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.token-item .token-value{font-size:24px;font-weight:700;color:#1d4ed8}
.token-item .token-detail{font-size:11px;color:var(--muted);margin-top:4px}
.insight-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-bottom:32px}
.insight{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
.insight h3{font-size:15px;margin-bottom:10px}
.insight p{font-size:13px;line-height:1.5;color:var(--muted);margin-bottom:8px}
.mini-table{width:100%;font-size:12px;border-collapse:collapse}
.mini-table th{position:static;font-size:10px;padding:6px 8px}
.mini-table td{padding:6px 8px}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-ok{background:var(--green)}.status-warn{background:var(--orange)}.status-muted{background:var(--muted)}
.metadata-snippet{font-family:'SF Mono','Fira Code',monospace;font-size:10px;color:var(--muted);white-space:pre-wrap;word-break:break-all}
.source-cell{max-width:220px;white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-height:1.35}
.source-link{color:inherit;text-decoration:none;overflow-wrap:anywhere;word-break:break-word}
.source-primary{font-weight:600;line-height:1.35}
.source-secondary{font-size:11px;color:var(--muted);line-height:1.35;margin-top:2px}
.ingestion-row{cursor:pointer}
.ingestion-row td:first-child::before{content:'\\25B6';margin-right:8px;font-size:10px;color:var(--muted);transition:.2s;display:inline-block}
.ingestion-row.open td:first-child::before{transform:rotate(90deg)}
.ingestion-parent-row td{background:#fff}
.page-row td{background:rgba(79,70,229,.03);font-size:12px}
.page-row td:first-child{padding-left:28px}
.page-row-expandable td:first-child::before{content:'\\25B6';margin-right:8px;font-size:10px;color:var(--muted);transition:.2s;display:inline-block}
.page-row-expandable.open td:first-child::before{transform:rotate(90deg)}
.table-action-cell{white-space:nowrap}
.inline-action-btn{padding:5px 10px;border-radius:6px;border:1px solid var(--border);background:#fff;color:var(--text);font-size:11px;font-weight:600;cursor:pointer}
.inline-action-btn:hover{border-color:var(--accent);color:var(--accent);background:rgba(79,70,229,.06)}
.inline-action-btn:disabled{opacity:.65;cursor:wait}
.chunk-row td{background:rgba(79,70,229,.06);font-size:12px;padding:8px 12px}
.chunk-row td:first-child{padding-left:52px}
.chunk-content{white-space:pre-wrap;word-break:break-word;max-width:760px;line-height:1.5}
.hidden-panel{display:none}
@media (max-width: 760px) {
  body{padding:12px}
  h1{font-size:24px}
  .subtitle{margin-bottom:16px}
  .toolbar{gap:8px;margin-bottom:18px}
  .toolbar button{flex:1 1 calc(50% - 8px);padding:10px 8px}
  .toolbar span{display:none}
  .summary-actions button{flex:1 1 100%;padding:12px}
  .kpi-grid,.token-grid,.insight-grid{grid-template-columns:1fr;gap:12px;margin-bottom:20px}
  .kpi,.token-summary,.insight{padding:14px;border-radius:8px}
  .kpi .value{font-size:24px}
  .token-item .token-value{font-size:22px}
  .section h2{font-size:17px}
  .table-wrap{max-height:420px}
  table{font-size:12px}
  th,td{padding:8px}
}
</style>
</head>
<body>
<div class="container" id="report-content">

<h1>Usage Report</h1>
<p class="subtitle" id="subtitle"></p>

<div class="toolbar">
  <button onclick="setDays(7)" id="btn-7">7 Days</button>
  <button onclick="setDays(14)" id="btn-14">14 Days</button>
  <button onclick="setDays(30)" id="btn-30">30 Days</button>
  <button onclick="setDays(90)" id="btn-90">90 Days</button>
  <button onclick="setDays(180)" id="btn-180">180 Days</button>
  <button onclick="setDays(365)" id="btn-365" class="active">All Time</button>
  <span style="flex:1"></span>
  <select id="tenant-filter" onchange="setTenant(this.value)" style="padding:8px 12px;border-radius:8px;font-size:13px;border:1px solid var(--border);background:var(--card);max-width:200px">
    <option value="">All Tenants</option>
  </select>
  <button onclick="downloadExcel()">Download Excel</button>
</div>

<!-- Token Summary -->
<div class="token-summary" id="token-summary"></div>

<div class="kpi-grid" id="kpis"></div>

<div class="insight-grid" id="usage-insights"></div>


<div id="details-panel">
<div class="section"><h2>Chat Sessions</h2><div class="table-wrap" style="max-height:700px"><table>
  <thead><tr><th>Session ID</th><th>Started</th><th title="Total messages in this session">Msgs</th><th title="Provider-reported input tokens">Prompt Tokens</th><th title="Provider-reported output tokens">Completion Tokens</th><th title="Gemini count_tokens totals for captured context text only">Captured Context Tokens</th><th title="Gemini count_tokens totals for visible message text">Message Tokens</th><th>Status</th><th>Price</th></tr></thead>
  <tbody id="sessions-table"></tbody>
</table></div></div>

<div class="section" id="token-log-section">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;border-bottom:1px solid var(--border);padding-bottom:8px">
    <h2 style="margin:0">Knowledge Ingestion</h2>
  </div>
  <div class="table-wrap"><table>
  <thead><tr><th><span class="th-with-info">Date<button type="button" class="info-icon" aria-label="Explain Date column" aria-expanded="false" data-tooltip-title="Date" data-tooltip="Table: token_usage_log&#10;Column: created_at&#10;Logic: shows the created_at timestamp of the ingestion embedding usage row. Expanded chunk rows show the chunk created_at timestamp." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Source<button type="button" class="info-icon" aria-label="Explain Source column" aria-expanded="false" data-tooltip-title="Source" data-tooltip="Table: file_uploads.original_filename or scraped_websites.original_url&#10;Logic: if request_metadata.file_id matches RAW.files.id, show file_uploads.original_filename; else if request_metadata.website_id matches RAW.websites.id, show scraped_websites.original_url. Expanded chunk rows show the chunk text itself." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Chunk Row Count<button type="button" class="info-icon" aria-label="Explain Chunk Row Count column" aria-expanded="false" data-tooltip-title="Chunk Row Count" data-tooltip="Table: document_chunks&#10;Logic: main rows use COUNT(*) grouped by document_id from RAW.file_chunk_stats / RAW.website_chunk_stats. Expanded chunk rows show the 1-based row number of that chunk within the document." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Content KB<button type="button" class="info-icon" aria-label="Explain Content KB column" aria-expanded="false" data-tooltip-title="Content KB" data-tooltip="Table: document_chunks&#10;Column: pg_column_size(content)&#10;Logic: main rows show grouped totals; expanded chunk rows show the stored size for that individual chunk content." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Embedding KB<button type="button" class="info-icon" aria-label="Explain Embedding KB column" aria-expanded="false" data-tooltip-title="Embedding KB" data-tooltip="Table: document_chunks&#10;Column: pg_column_size(embedding)&#10;Logic: main rows show grouped totals; expanded chunk rows show the stored size for that individual chunk embedding." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Model<button type="button" class="info-icon" aria-label="Explain Model column" aria-expanded="false" data-tooltip-title="Model" data-tooltip="Table: token_usage_log&#10;Column: model&#10;Logic: shows the embedding model recorded for the ingestion usage row, and the same model is shown on expanded chunk rows." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Embedding Tokens<button type="button" class="info-icon" aria-label="Explain Embedding Tokens column" aria-expanded="false" data-tooltip-title="Embedding Tokens" data-tooltip="Table: token_usage_log&#10;Column: total_tokens&#10;Logic: shows the logged embedding token count for the ingestion usage row." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Chars<button type="button" class="info-icon" aria-label="Explain Chars column" aria-expanded="false" data-tooltip-title="Chars" data-tooltip="Tables: token_usage_log.request_metadata and document_chunks&#10;Logic: main rows show request_metadata.input_character_count; expanded chunk rows show char_length(content) for that chunk." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Words<button type="button" class="info-icon" aria-label="Explain Words column" aria-expanded="false" data-tooltip-title="Words" data-tooltip="Tables: token_usage_log.request_metadata and document_chunks&#10;Logic: main rows show request_metadata.input_word_count; expanded chunk rows show the whitespace-delimited word count for that chunk." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Char/Token Ratio<button type="button" class="info-icon" aria-label="Explain Char/Token Ratio column" aria-expanded="false" data-tooltip-title="Char/Token Ratio" data-tooltip="Tables: token_usage_log.request_metadata and token_usage_log&#10;Columns: input_character_count and total_tokens&#10;Logic: character_count divided by the logged embedding token count for the ingestion usage row. Expanded chunk rows leave this blank because there is no per-chunk token value stored." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Download CSV<button type="button" class="info-icon" aria-label="Explain Download CSV column" aria-expanded="false" data-tooltip-title="Download CSV" data-tooltip="Logic: parent ingestion rows can export their child chunk rows to a CSV file for manual tally. Child rows themselves do not show a download button." onclick="toggleHeaderTooltip(event)">i</button></span></th><th><span class="th-with-info">Price<button type="button" class="info-icon" aria-label="Explain Price column" aria-expanded="false" data-tooltip-title="Price" data-tooltip="Logic: calculated estimated embedding cost for the parent row using the model pricing and the logged embedding token count." onclick="toggleHeaderTooltip(event)">i</button></span></th></tr></thead>
  <tbody id="token-log-table"></tbody>
</table></div></div>
</div>

</div>

<div id="header-tooltip-popover" class="header-tooltip-popover" role="dialog" aria-live="polite" aria-hidden="true"></div>
<div id="text-popup-backdrop" class="text-popup-backdrop" role="dialog" aria-modal="true" aria-hidden="true">
  <div class="text-popup">
    <div class="text-popup-header">
      <div id="text-popup-title" class="text-popup-title">Text Details</div>
      <button type="button" class="text-popup-close" onclick="closeTextPopup()">Close</button>
    </div>
    <div class="text-popup-body">
      <pre id="text-popup-content" class="text-popup-pre"></pre>
    </div>
  </div>
</div>

<script id="report-raw-data" type="application/json">"""
        + data_json
        + """</script>

<script>
// === DATA ===
const RAW = JSON.parse(document.getElementById('report-raw-data').textContent || '{}');
let currentDays = 365;
console.log('RAW keys:', RAW ? Object.keys(RAW) : 'empty');

// === HELPERS ===
const fmt = n => (n||0).toLocaleString();
const fmtDate = s => s ? new Date(s).toLocaleDateString('en-CA') : '-';
const fmtDateTime = s => s ? new Date(s).toLocaleString('en-CA',{dateStyle:'short',timeStyle:'short'}) : '-';
const EMBEDDING_PRICING_PER_1M = {
  'text-embedding-3-small': 0.02,
};
const badge = s => `<span class="badge badge-${s||'active'}">${s||'active'}</span>`;
const cutoff = days => { const d=new Date(); d.setDate(d.getDate()-days); return d.toISOString(); };
const trunc = (s,n) => s && s.length>n ? s.substring(0,n)+'...' : (s||'-');
const escHtml = s => s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';
const FILE_SOURCE_MAP = Object.fromEntries((RAW.files || []).map(f => [String(f.id), f.original_filename || '']));
const WEBSITE_SOURCE_MAP = Object.fromEntries((RAW.websites || []).map(w => [String(w.id), w.original_url || '']));
const CHAT_MESSAGE_BY_ID = Object.fromEntries((RAW.chat_messages || []).map(m => [String(m.id), m]));
const INGESTION_CHUNK_CACHE = new Map();
const INGESTION_CHUNK_REQUESTS = new Map();
let CURRENT_INGESTION_VIEW = {
  websiteUsageById: new Map(),
  fileUsageById: new Map(),
  websiteRootsById: new Map(),
  websiteChildrenByParentId: new Map(),
  fileRowsById: new Map(),
};
let activeHeaderTooltipButton = null;

function openTextPopup(title, text) {
  const backdrop = document.getElementById('text-popup-backdrop');
  const titleEl = document.getElementById('text-popup-title');
  const contentEl = document.getElementById('text-popup-content');
  if(!backdrop || !titleEl || !contentEl) return;
  titleEl.textContent = title || 'Text Details';
  contentEl.textContent = text || 'No text available.';
  backdrop.style.display = 'flex';
  backdrop.setAttribute('aria-hidden', 'false');
}

function closeTextPopup() {
  const backdrop = document.getElementById('text-popup-backdrop');
  const contentEl = document.getElementById('text-popup-content');
  if(!backdrop || !contentEl) return;
  backdrop.style.display = 'none';
  backdrop.setAttribute('aria-hidden', 'true');
  contentEl.textContent = '';
}

function filterByDate(arr, days, dateField='created_at') {
  const c = cutoff(days);
  return arr.filter(r => (r[dateField]||'') >= c);
}

function closeHeaderTooltip() {
  const popover = document.getElementById('header-tooltip-popover');
  if (!popover) return;
  popover.style.display = 'none';
  popover.setAttribute('aria-hidden', 'true');
  popover.innerHTML = '';
  if (activeHeaderTooltipButton) {
    activeHeaderTooltipButton.setAttribute('aria-expanded', 'false');
    activeHeaderTooltipButton = null;
  }
}

function toggleHeaderTooltip(event) {
  event.preventDefault();
  event.stopPropagation();
  const btn = event.currentTarget;
  const popover = document.getElementById('header-tooltip-popover');
  if (!popover) return;

  if (activeHeaderTooltipButton === btn && popover.style.display === 'block') {
    closeHeaderTooltip();
    return;
  }

  if (activeHeaderTooltipButton) {
    activeHeaderTooltipButton.setAttribute('aria-expanded', 'false');
  }

  activeHeaderTooltipButton = btn;
  btn.setAttribute('aria-expanded', 'true');
  popover.innerHTML = `<div class="header-tooltip-title">${escHtml(btn.dataset.tooltipTitle || '')}</div><div class="header-tooltip-body">${escHtml(btn.dataset.tooltip || '').replace(/\\n/g, '<br>')}</div>`;
  popover.style.display = 'block';
  popover.setAttribute('aria-hidden', 'false');

  const rect = btn.getBoundingClientRect();
  const popRect = popover.getBoundingClientRect();
  let left = Math.min(window.innerWidth - popRect.width - 12, Math.max(12, rect.left - 8));
  let top = rect.bottom + 8;
  if (top + popRect.height > window.innerHeight - 12) {
    top = Math.max(12, rect.top - popRect.height - 8);
  }
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}

// Tenant filtering - server-side
let currentTenant = '';
const TENANTS = RAW.tenants || {};
const BASE_URL = window.location.pathname.replace('/usage', '');

async function setTenant(id) {
  currentTenant = id;
  const url = id ? `${BASE_URL}/usage?tenant=${id}` : `${BASE_URL}/usage`;
  window.location.href = url;
}

function getTenantFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get('tenant') || '';
}

// Populate tenant dropdown
function initTenantFilter() {
  const sel = document.getElementById('tenant-filter');
  if (!sel) return;
  Object.entries(TENANTS).forEach(([id, t]) => {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = t.name || t.slug;
    sel.appendChild(opt);
  });
}

// Extract cache tokens from request_metadata JSONB
function getCacheTokens(meta) {
  if(!meta) return {read:0, write:0};
  let obj = meta;
  if(typeof meta === 'string') { try { obj = JSON.parse(meta); } catch(e) { return {read:0,write:0}; } }
  return {
    read: obj.cache_read_tokens || 0,
    write: obj.cache_write_tokens || 0
  };
}
function parseMeta(meta) {
  if(!meta) return {};
  if(typeof meta === 'string') { try { return JSON.parse(meta); } catch(e) { return {}; } }
  return meta || {};
}
function callTypeLabel(callType) {
  const labels = {
    agent_stream: 'Chat responses',
    rag: 'RAG/chat',
    embedding: 'Embeddings',
    equation_vision: 'Equation vision OCR',
    cache_create: 'Gemini cache creation',
  };
  return labels[callType] || callType || 'Unknown';
}
function isIngestionUsage(row) {
  if ((row.api_call_type || '') !== 'embedding') return false;
  const meta = parseMeta(row.request_metadata);
  const workflow = meta.ingestion_workflow || '';
  return workflow === 'file_upload_pipeline'
    || workflow === 'web_scrape_pipeline'
    || !!meta.file_id
    || !!meta.website_id
    || !!meta.source_url
    || !!meta.webpage_name
    || !!meta.filename
    || !!meta.display_name;
}
function groupByCallType(rows) {
  const grouped = {};
  rows.forEach(r => {
    const key = r.api_call_type || 'unknown';
    if(!grouped[key]) grouped[key] = {call_type:key, requests:0, prompt:0, completion:0, total:0, cacheRead:0, cacheWrite:0, tools:0};
    const meta = parseMeta(r.request_metadata);
    const cache = getCacheTokens(r.request_metadata);
    grouped[key].requests += 1;
    grouped[key].prompt += r.prompt_tokens || 0;
    grouped[key].completion += r.completion_tokens || 0;
    grouped[key].total += r.total_tokens || 0;
    grouped[key].cacheRead += cache.read;
    grouped[key].cacheWrite += cache.write;
    grouped[key].tools += meta.tool_call_count || 0;
  });
  return Object.values(grouped).sort((a,b) => (b.total || (b.prompt + b.completion)) - (a.total || (a.prompt + a.completion)));
}
function payloadChars(meta) {
  return meta.input_character_count || meta.system_prompt_character_count || 0;
}
function payloadWords(meta) {
  return meta.input_word_count || 0;
}
function payloadBytes(meta) {
  return meta.input_size_bytes || meta.image_size_bytes || meta.system_prompt_size_bytes || 0;
}
function strictIngestionSource(meta) {
  if(meta.source_url) return meta.source_url;
  if(meta.url) return meta.url;
  if(meta.file_id) return FILE_SOURCE_MAP[String(meta.file_id)] || '';
  if(meta.website_id) return WEBSITE_SOURCE_MAP[String(meta.website_id)] || '';
  return meta.display_name || meta.filename || meta.webpage_name || '';
}
function normalizeSourceKey(value) {
  const normalized = String(value || '').trim();
  if(!normalized) return '';
  return normalized.replace(/\/+$/,'');
}
function parseChunkMetadata(chunk) {
  if(!chunk || chunk.metadata == null) return {};
  if(typeof chunk.metadata === 'string') {
    try { return JSON.parse(chunk.metadata); } catch(e) { return {}; }
  }
  return chunk.metadata || {};
}
function getChunkPageUrl(chunk) {
  const meta = parseChunkMetadata(chunk);
  return chunk.page_url || meta.url || '';
}
function getChunkPageTitle(chunk) {
  const meta = parseChunkMetadata(chunk);
  return chunk.page_title || meta.title || '';
}
function sortRowsByCreatedDesc(rows) {
  return [...(rows || [])].sort((a,b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
}
function buildUsageMaps(rows) {
  const websiteUsageById = new Map();
  const fileUsageById = new Map();
  (rows || []).forEach(row => {
    const meta = parseMeta(row.request_metadata);
    if(meta.website_id) {
      const key = String(meta.website_id);
      if(!websiteUsageById.has(key)) websiteUsageById.set(key, []);
      websiteUsageById.get(key).push(row);
    }
    if(meta.file_id) {
      const key = String(meta.file_id);
      if(!fileUsageById.has(key)) fileUsageById.set(key, []);
      fileUsageById.get(key).push(row);
    }
  });
  websiteUsageById.forEach((value, key) => websiteUsageById.set(key, sortRowsByCreatedDesc(value)));
  fileUsageById.forEach((value, key) => fileUsageById.set(key, sortRowsByCreatedDesc(value)));
  return { websiteUsageById, fileUsageById };
}
function summarizeUsageRows(rows) {
  const sorted = sortRowsByCreatedDesc(rows);
  const totals = sorted.reduce((acc, row) => {
    const meta = parseMeta(row.request_metadata);
    acc.tokens += Number(row.total_tokens || row.prompt_tokens || 0);
    acc.charCount += Number(meta.input_character_count || 0);
    acc.wordCount += Number(meta.input_word_count || 0);
    acc.sizeBytes += Number(meta.input_size_bytes || 0);
    return acc;
  }, { tokens: 0, charCount: 0, wordCount: 0, sizeBytes: 0 });
  return {
    createdAt: sorted[0]?.created_at || '',
    model: sorted.find(row => row.model)?.model || '',
    tokens: totals.tokens,
    charCount: totals.charCount,
    wordCount: totals.wordCount,
    sizeBytes: totals.sizeBytes,
  };
}
function estimatedEmbeddingCostUsd(model, tokens) {
  const unitPrice = EMBEDDING_PRICING_PER_1M[String(model || '').trim().toLowerCase()];
  const tokenCount = Number(tokens || 0);
  if(!unitPrice || tokenCount <= 0) return 0;
  return (tokenCount / 1000000) * unitPrice;
}
function fmtUsd(value) {
  const amount = Number(value || 0);
  if(!(amount > 0)) return '-';
  if(amount < 0.01) return `$${amount.toFixed(6)}`;
  return `$${amount.toFixed(4)}`;
}
function geminiPricingForChatModel(model) {
  const normalizedModel = String(model || '').toLowerCase();
  if(normalizedModel.includes('2.5-flash-lite')) {
    return {
      standard_input: 0.10,
      completion: 0.40,
      cache_read: 0.025,
      cache_write: 0.0,
    };
  }
  if(normalizedModel.includes('1.5-flash')) {
    return {
      standard_input: 0.075,
      completion: 0.30,
      cache_read: 0.01875,
      cache_write: 0.0,
    };
  }
  return {
    standard_input: 0.10,
    completion: 0.40,
    cache_read: 0.01,
    cache_write: 0.10,
  };
}
function usageRowCostUsd(row) {
  const meta = parseMeta(row && row.request_metadata);
  const direct = Number(meta.cost_usd ?? row.cost_usd ?? 0);
  if(Number.isFinite(direct) && direct > 0) return direct;
  const provider = String(meta.provider ?? row.provider ?? '').toLowerCase();
  const model = String(meta.model ?? row.model ?? '');
  const pricing = meta.pricing_usd_per_1m || (provider === 'gemini' ? geminiPricingForChatModel(model) : null);
  if(!pricing) return 0;

  const promptTokens = Number(row && row.prompt_tokens || 0);
  const completionTokens = Number(row && row.completion_tokens || 0);
  const cacheRead = Number(meta.cache_read_tokens || 0);
  const cacheWrite = Number(meta.cache_write_tokens || 0);
  const standardInput = Math.max(0, promptTokens - cacheRead);
  const inputRate = Number(pricing.standard_input || 0);
  const outputRate = Number(pricing.completion || 0);
  const cacheReadRate = Number(pricing.cache_read || 0);
  const cacheWriteRate = Number(pricing.cache_write || 0);
  const computed = (
    (standardInput * inputRate) +
    (completionTokens * outputRate) +
    (cacheRead * cacheReadRate) +
    (cacheWrite * cacheWriteRate)
  ) / 1000000;
  return Number.isFinite(computed) && computed > 0 ? computed : 0;
}
function chatUnitRateLabel(model) {
  const resolvedModel = String(model || '').trim() || 'gemini-2.5-flash-lite';
  const pricing = geminiPricingForChatModel(resolvedModel);
  return `${resolvedModel} • In $${Number(pricing.standard_input || 0).toFixed(3)}/1M • Out $${Number(pricing.completion || 0).toFixed(3)}/1M • Cache $${Number(pricing.cache_read || 0).toFixed(3)}/1M`;
}
function ingestionUnitRateLabel(model) {
  const resolvedModel = String(model || '').trim() || 'text-embedding-3-small';
  const unitRate = Number(EMBEDDING_PRICING_PER_1M[resolvedModel] || 0);
  return `${resolvedModel} • $${unitRate.toFixed(2)}/1M tokens`;
}
function summarizeWebsiteChunksByPage(chunks) {
  const grouped = new Map();
  (chunks || []).forEach(chunk => {
    const pageUrl = getChunkPageUrl(chunk);
    const key = normalizeSourceKey(pageUrl) || '__unknown__';
    if(!grouped.has(key)) {
      grouped.set(key, {
        pageKey: key,
        pageUrl,
        pageTitle: getChunkPageTitle(chunk),
        chunkCount: 0,
        contentStorageBytes: 0,
        embeddingStorageBytes: 0,
        charCount: 0,
        wordCount: 0,
        sizeBytes: 0,
        createdAt: chunk.created_at || '',
      });
    }
    const summary = grouped.get(key);
    summary.pageUrl = summary.pageUrl || pageUrl;
    summary.pageTitle = summary.pageTitle || getChunkPageTitle(chunk);
    summary.chunkCount += 1;
    summary.contentStorageBytes += Number(chunk.content_storage_bytes || 0);
    summary.embeddingStorageBytes += Number(chunk.embedding_storage_bytes || 0);
    summary.charCount += Number(chunk.char_count || 0);
    summary.wordCount += Number(chunk.word_count || 0);
    summary.sizeBytes += Number(chunk.size_bytes || 0);
    if(String(chunk.created_at || '') > String(summary.createdAt || '')) summary.createdAt = chunk.created_at || summary.createdAt;
  });
  return grouped;
}
function renderSourceCell(primary, secondary='') {
  const primaryText = escHtml(primary || '-');
  const secondaryText = secondary ? `<div class="source-secondary">${escHtml(secondary)}</div>` : '';
  return `<div class="source-primary">${primaryText}</div>${secondaryText}`;
}
function joinSecondaryParts(parts) {
  return (parts || []).filter(Boolean).join(' • ');
}
function buildWebsiteChildrenMap(websites) {
  const websiteRootsById = new Map();
  const websiteChildrenByParentId = new Map();
  (websites || []).forEach(site => {
    const siteId = String(site.id || '');
    if(!site.parent_id) {
      websiteRootsById.set(siteId, site);
      return;
    }
    const parentId = String(site.parent_id);
    if(!websiteChildrenByParentId.has(parentId)) websiteChildrenByParentId.set(parentId, []);
    websiteChildrenByParentId.get(parentId).push(site);
  });
  websiteChildrenByParentId.forEach((rows, key) => websiteChildrenByParentId.set(key, sortRowsByCreatedDesc(rows)));
  return { websiteRootsById, websiteChildrenByParentId };
}
function buildWebsitePageRows(documentId, parentWebsite, childWebsites, chunks) {
  const pageSummaries = summarizeWebsiteChunksByPage(chunks);
  const usageRows = CURRENT_INGESTION_VIEW.websiteUsageById.get(String(documentId)) || [];
  const parentSourceName = parentWebsite?.original_url || '';
  const rowsByKey = new Map();

  function ensureRow(key, fallbackId='') {
    if(!rowsByKey.has(key)) {
      rowsByKey.set(key, {
        rowId: fallbackId || key,
        pageKey: key,
        pageUrl: '',
        pageTitle: '',
        createdAt: '',
        model: '',
        embeddingTokens: 0,
        charCount: 0,
        wordCount: 0,
        sizeBytes: 0,
        chunkCount: 0,
        contentStorageBytes: 0,
        embeddingStorageBytes: 0,
        isRootPage: false,
      });
    }
    return rowsByKey.get(key);
  }

  (childWebsites || []).forEach(site => {
    const key = normalizeSourceKey(site.original_url) || `child:${site.id}`;
    const row = ensureRow(key, String(site.id || key));
    row.pageUrl = row.pageUrl || site.original_url || '';
    row.pageTitle = row.pageTitle || site.title || '';
    if(String(site.created_at || '') > String(row.createdAt || '')) row.createdAt = site.created_at || row.createdAt;
    row.embeddingTokens = Math.max(row.embeddingTokens || 0, Number(site.embedding_token_count || 0));
    row.charCount = Math.max(row.charCount || 0, Number(site.embedding_character_count ?? site.char_count ?? 0));
    row.wordCount = Math.max(row.wordCount || 0, Number(site.embedding_word_count ?? 0));
    row.sizeBytes = Math.max(row.sizeBytes || 0, Number(site.file_size || 0));
  });

  usageRows.forEach(row => {
    const meta = parseMeta(row.request_metadata);
    const pageUrl = meta.source_url || meta.url || '';
    const key = normalizeSourceKey(pageUrl) || '__unknown__';
    const summary = pageSummaries.get(key);
    const pageRow = ensureRow(key, String(row.id || key));
    pageRow.pageUrl = pageRow.pageUrl || pageUrl || summary?.pageUrl || '';
    pageRow.pageTitle = pageRow.pageTitle || meta.webpage_name || summary?.pageTitle || '';
    if(String(row.created_at || '') > String(pageRow.createdAt || '')) pageRow.createdAt = row.created_at || pageRow.createdAt;
    pageRow.model = pageRow.model || row.model || '';
    pageRow.embeddingTokens += Number(row.total_tokens || row.prompt_tokens || 0);
    pageRow.charCount = Math.max(pageRow.charCount || 0, Number(meta.input_character_count ?? summary?.charCount ?? 0));
    pageRow.wordCount = Math.max(pageRow.wordCount || 0, Number(meta.input_word_count ?? summary?.wordCount ?? 0));
    pageRow.sizeBytes = Math.max(pageRow.sizeBytes || 0, Number(meta.input_size_bytes ?? summary?.sizeBytes ?? 0));
  });

  pageSummaries.forEach(summary => {
    const pageRow = ensureRow(summary.pageKey, `summary:${summary.pageKey}`);
    pageRow.pageUrl = pageRow.pageUrl || summary.pageUrl || '';
    pageRow.pageTitle = pageRow.pageTitle || summary.pageTitle || '';
    if(String(summary.createdAt || '') > String(pageRow.createdAt || '')) pageRow.createdAt = summary.createdAt || pageRow.createdAt;
    pageRow.chunkCount = Number(summary.chunkCount || 0);
    pageRow.contentStorageBytes = Number(summary.contentStorageBytes || 0);
    pageRow.embeddingStorageBytes = Number(summary.embeddingStorageBytes || 0);
    pageRow.charCount = Math.max(pageRow.charCount || 0, Number(summary.charCount || 0));
    pageRow.wordCount = Math.max(pageRow.wordCount || 0, Number(summary.wordCount || 0));
    pageRow.sizeBytes = Math.max(pageRow.sizeBytes || 0, Number(summary.sizeBytes || 0));
  });

  rowsByKey.forEach(pageRow => {
    pageRow.pageUrl = pageRow.pageUrl || parentSourceName || '';
    if(!pageRow.pageTitle && normalizeSourceKey(pageRow.pageUrl) === normalizeSourceKey(parentSourceName)) {
      pageRow.pageTitle = parentWebsite?.title || '';
    }
    pageRow.isRootPage = normalizeSourceKey(pageRow.pageUrl) === normalizeSourceKey(parentSourceName);
  });

  return Array.from(rowsByKey.values()).sort((a,b) =>
    String(b.createdAt || '').localeCompare(String(a.createdAt || ''))
    || String(a.pageUrl || '').localeCompare(String(b.pageUrl || ''))
  );
}
function countWebsitePages(parentWebsite, childWebsites, usageRows) {
  const pageKeys = new Set();
  const rootUrl = normalizeSourceKey(parentWebsite?.original_url || '');
  if(rootUrl) pageKeys.add(rootUrl);

  (childWebsites || []).forEach(site => {
    const key = normalizeSourceKey(site.original_url || '');
    if(key) pageKeys.add(key);
  });

  (usageRows || []).forEach(row => {
    const meta = parseMeta(row.request_metadata);
    const key = normalizeSourceKey(meta.source_url || meta.url || '');
    if(key) pageKeys.add(key);
  });

  const explicitPagesScraped = Number(parentWebsite?.pages_scraped || 0);
  return Math.max(pageKeys.size, explicitPagesScraped, rootUrl ? 1 : 0);
}
function buildIngestionParentRows(files, websites) {
  const parentRows = [];
  const rootWebsites = (websites || []).filter(site => !site.parent_id);

  rootWebsites.forEach(site => {
    const siteId = String(site.id);
    const usageRows = CURRENT_INGESTION_VIEW.websiteUsageById.get(siteId) || [];
    const usageSummary = summarizeUsageRows(usageRows);
    const chunkStats = RAW.website_chunk_stats[siteId] || {};
    const childPages = CURRENT_INGESTION_VIEW.websiteChildrenByParentId.get(siteId) || [];
    const pageCount = countWebsitePages(site, childPages, usageRows);
    const sourceSecondary = joinSecondaryParts([
      site.title || '',
      pageCount ? `${fmt(pageCount)} pages` : '',
    ]);

    parentRows.push({
      rowKind: 'website-parent',
      documentId: siteId,
      documentType: 'website',
      sourceName: site.original_url || '',
      sourceSecondary,
      createdAt: usageSummary.createdAt || site.created_at || '',
      model: usageSummary.model || '',
      embeddingTokens: Number(usageSummary.tokens || site.embedding_token_count || 0),
      priceUsd: estimatedEmbeddingCostUsd(usageSummary.model || '', Number(usageSummary.tokens || site.embedding_token_count || 0)),
      charCount: Number(usageSummary.charCount || site.embedding_character_count || site.char_count || 0),
      wordCount: Number(usageSummary.wordCount || site.embedding_word_count || 0),
      sizeBytes: Number(usageSummary.sizeBytes || site.file_size || 0),
      chunkCount: Number(chunkStats.chunk_count || 0),
      contentPretty: fmtKb(chunkStats.content_storage_bytes),
      embeddingPretty: fmtKb(chunkStats.embedding_storage_bytes),
      // Multi-page websites expand to child pages; single-page websites expand directly to chunks.
      expandable: childPages.length > 0 || Number(chunkStats.chunk_count || 0) > 0,
      downloadable: childPages.length > 0 || Number(chunkStats.chunk_count || 0) > 0 || usageRows.length > 0,
    });
  });

  (files || []).forEach(file => {
    const fileId = String(file.id);
    const usageRows = CURRENT_INGESTION_VIEW.fileUsageById.get(fileId) || [];
    const usageSummary = summarizeUsageRows(usageRows);
    const chunkStats = RAW.file_chunk_stats[fileId] || {};
    const sourceSecondary = joinSecondaryParts([
      file.display_name && file.display_name !== file.original_filename ? file.display_name : '',
      file.file_extension ? `.${file.file_extension}` : '',
    ]);

    parentRows.push({
      rowKind: 'file-parent',
      documentId: fileId,
      documentType: 'file',
      sourceName: file.original_filename || file.display_name || '',
      sourceSecondary,
      createdAt: usageSummary.createdAt || file.created_at || '',
      model: usageSummary.model || '',
      embeddingTokens: Number(usageSummary.tokens || file.embedding_token_count || 0),
      priceUsd: estimatedEmbeddingCostUsd(usageSummary.model || '', Number(usageSummary.tokens || file.embedding_token_count || 0)),
      charCount: Number(usageSummary.charCount || file.embedding_character_count || file.char_count || 0),
      wordCount: Number(usageSummary.wordCount || file.embedding_word_count || 0),
      sizeBytes: Number(usageSummary.sizeBytes || file.file_size || 0),
      chunkCount: Number(chunkStats.chunk_count || 0),
      contentPretty: fmtKb(chunkStats.content_storage_bytes),
      embeddingPretty: fmtKb(chunkStats.embedding_storage_bytes),
      expandable: Number(chunkStats.chunk_count || 0) > 0,
      downloadable: Number(chunkStats.chunk_count || 0) > 0,
    });
  });

  return parentRows.sort((a,b) =>
    String(b.createdAt || '').localeCompare(String(a.createdAt || ''))
    || String(a.sourceName || '').localeCompare(String(b.sourceName || ''))
  );
}
function renderIngestionParentRow(row) {
  const rowClasses = [row.expandable ? 'ingestion-row' : '', 'ingestion-parent-row'].filter(Boolean).join(' ');
  const ratio = row.embeddingTokens > 0 && row.charCount > 0 ? (row.charCount / row.embeddingTokens).toFixed(2) : '-';
  const clickAttr = row.expandable ? 'onclick="toggleIngestionParentRow(this)"' : '';
  const downloadCell = row.downloadable
    ? `<button type="button" class="inline-action-btn" onclick="downloadIngestionCsv(event, this)">Download CSV</button>`
    : '-';

  return `<tr class="${rowClasses}"
      data-row-kind="${escHtml(row.rowKind)}"
      data-document-id="${escHtml(row.documentId)}"
      data-document-type="${escHtml(row.documentType)}"
      data-source-name="${escHtml(row.sourceName)}"
      data-source-secondary="${escHtml(row.sourceSecondary || '')}"
      data-parent-created-at="${escHtml(row.createdAt || '')}"
      data-embedding-model="${escHtml(row.model || '')}"
      data-embedding-tokens="${row.embeddingTokens ? String(row.embeddingTokens) : ''}"
      ${clickAttr}>
      <td>${fmtDateTime(row.createdAt)}</td>
      <td class="source-cell" title="${escHtml(row.sourceName)}">${renderSourceCell(row.sourceName, row.sourceSecondary || '')}</td>
      <td>${fmt(row.chunkCount)}</td>
      <td>${row.contentPretty || '-'}</td>
      <td>${row.embeddingPretty || '-'}</td>
      <td>${row.model ? escHtml(row.model) : '-'}</td>
      <td class="token-cell">${row.embeddingTokens ? fmt(row.embeddingTokens) : '-'}</td>
      <td>${row.charCount ? fmt(row.charCount) : '-'}</td>
      <td>${row.wordCount ? fmt(row.wordCount) : '-'}</td>
      <td>${ratio}</td>
      <td class="table-action-cell">${downloadCell}</td>
      <td>${fmtUsd(row.priceUsd)}</td>
    </tr>`;
}
function createWebsitePageRowElement(page, parentDocumentId) {
  const rowEl = document.createElement('tr');
  const isExpandable = Number(page.chunkCount || 0) > 0;
  rowEl.className = `page-row${isExpandable ? ' page-row-expandable' : ''}`;
  rowEl.dataset.rowKind = 'website-page';
  rowEl.dataset.parentDocumentId = String(parentDocumentId || '');
  rowEl.dataset.pageKey = String(page.pageKey || '');
  rowEl.dataset.pageUrl = String(page.pageUrl || '');
  rowEl.dataset.sourceName = String(page.pageUrl || '');
  rowEl.dataset.sourceSecondary = String(page.pageTitle || '');
  rowEl.dataset.parentCreatedAt = String(page.createdAt || '');
  rowEl.dataset.embeddingModel = String(page.model || '');
  rowEl.dataset.embeddingTokens = page.embeddingTokens ? String(page.embeddingTokens) : '';
  if(isExpandable) rowEl.setAttribute('onclick', 'toggleWebsitePageRow(this)');

  const secondary = joinSecondaryParts([
    page.pageTitle || '',
    page.isRootPage ? 'Root page' : '',
  ]);
  const ratio = page.embeddingTokens > 0 && page.charCount > 0 ? (page.charCount / page.embeddingTokens).toFixed(2) : '-';
  const downloadCell = isExpandable
    ? `<button type="button" class="inline-action-btn" onclick="downloadIngestionCsv(event, this)">Download CSV</button>`
    : '-';

  rowEl.innerHTML = `
    <td>${fmtDateTime(page.createdAt)}</td>
    <td class="source-cell" title="${escHtml(page.pageUrl || '')}">${renderSourceCell(page.pageUrl || 'Unmapped page', secondary)}</td>
    <td>${fmt(page.chunkCount)}</td>
    <td>${page.contentStorageBytes ? fmtKb(page.contentStorageBytes) : '-'}</td>
    <td>${page.embeddingStorageBytes ? fmtKb(page.embeddingStorageBytes) : '-'}</td>
    <td>${page.model ? escHtml(page.model) : '-'}</td>
    <td class="token-cell">${page.embeddingTokens ? fmt(page.embeddingTokens) : '-'}</td>
    <td>${page.charCount ? fmt(page.charCount) : '-'}</td>
    <td>${page.wordCount ? fmt(page.wordCount) : '-'}</td>
    <td>${ratio}</td>
    <td class="table-action-cell">${downloadCell}</td>
    <td>-</td>
  `;
  return rowEl;
}
function createChunkRowElement(chunk, embeddingModel='') {
  const rowEl = document.createElement('tr');
  rowEl.className = 'chunk-row';
  const chunkLabel = chunk.chunk_row_number != null
    ? `Chunk ${fmt(chunk.chunk_row_number)}`
    : `Chunk ${fmt(Number(chunk.chunk_index || 0) + 1)}`;
  const preview = chunk.content ? String(chunk.content).trim() : '';
  rowEl.innerHTML = `
    <td>${fmtDateTime(chunk.created_at)}</td>
    <td class="source-cell">
      <div class="source-primary">${escHtml(chunkLabel)}</div>
      <div class="source-secondary chunk-content">${escHtml(preview || '-')}</div>
    </td>
    <td></td>
    <td>${chunk.content_storage_bytes == null ? '-' : fmtKb(chunk.content_storage_bytes)}</td>
    <td>${chunk.embedding_storage_bytes == null ? '-' : fmtKb(chunk.embedding_storage_bytes)}</td>
    <td>${embeddingModel ? escHtml(embeddingModel) : '-'}</td>
    <td>-</td>
    <td>${chunk.char_count == null ? '-' : fmt(chunk.char_count)}</td>
    <td>${chunk.word_count == null ? '-' : fmt(chunk.word_count)}</td>
    <td>-</td>
    <td></td>
    <td></td>
  `;
  return rowEl;
}
function fmtBytes(bytes) {
  bytes = Number(bytes || 0);
  if(!bytes) return '-';
  if(bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  if(bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${fmt(bytes)} B`;
}
function fmtKb(bytes) {
  bytes = Number(bytes || 0);
  if(!bytes) return '-';
  return `${(bytes / 1024).toFixed(1)} KB`;
}
function safeFileNameSegment(value) {
  return String(value || 'document')
    .replace(/^https?:\/\//i, '')
    .replace(/[^a-z0-9]+/gi, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80) || 'document';
}
function csvCell(value) {
  const normalized = value == null
    ? ''
    : (typeof value === 'object' ? JSON.stringify(value) : String(value));
  return `"${normalized.replace(/"/g, '""')}"`;
}
function downloadCsvFile(filename, rows) {
  const headers = rows.length ? Object.keys(rows[0]) : [];
  const csvLines = [headers.map(csvCell).join(',')];
  rows.forEach(row => {
    csvLines.push(headers.map(header => csvCell(row[header])).join(','));
  });
  const blob = new Blob([String.fromCharCode(0xFEFF) + csvLines.join('\\r\\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
function ingestionChunkCacheKey(documentId, documentType) {
  return `${documentType}:${documentId}`;
}
async function fetchIngestionChunks(documentId, documentType) {
  const cacheKey = ingestionChunkCacheKey(documentId, documentType);
  if (INGESTION_CHUNK_CACHE.has(cacheKey)) return INGESTION_CHUNK_CACHE.get(cacheKey);
  if (INGESTION_CHUNK_REQUESTS.has(cacheKey)) return INGESTION_CHUNK_REQUESTS.get(cacheKey);

  const query = new URLSearchParams({
    document_id: documentId,
    document_type: documentType,
  });
  if (currentTenant) query.set('tenant', currentTenant);

  const request = fetch(`${BASE_URL}/usage/chunks?${query.toString()}`, { credentials: 'include' })
    .then(async response => {
      if (!response.ok) throw new Error('Failed to load chunk rows');
      const payload = await response.json();
      const chunks = payload.chunks || [];
      INGESTION_CHUNK_CACHE.set(cacheKey, chunks);
      return chunks;
    })
    .finally(() => {
      INGESTION_CHUNK_REQUESTS.delete(cacheKey);
    });

  INGESTION_CHUNK_REQUESTS.set(cacheKey, request);
  return request;
}
function payloadTextChunks(meta) {
  const chunks = meta.input_text_chunks;
  if(Array.isArray(chunks)) {
    if(chunks.length === 1 && (meta.batch_size || 0) > 1 && chunks[0] && chunks[0].includes('\\\\n---\\\\n')) {
      return chunks[0].split('\\\\n---\\\\n');
    }
    return chunks;
  }
  if(meta.input_text) return [meta.input_text];
  return [];
}
function popupNumber(value, title, text) {
  const numericValue = Number(value || 0);
  if(!(numericValue > 0) || !text) return fmt(value);
  const encodedTitle = JSON.stringify(title || 'Text Details');
  const encodedText = JSON.stringify(text || '');
  return `<button type="button" class="number-link" onclick='openTextPopup(${encodedTitle}, ${encodedText})'>${fmt(value)}</button>`;
}
function nonIngestionUsageForSession(sessionId) {
  return (RAW.token_usage_log || [])
    .filter(r => r.session_id === sessionId && !isIngestionUsage(r))
    .sort((a,b) => (a.created_at||'').localeCompare(b.created_at||''));
}
function sessionPriceUsd(sessionId) {
  return nonIngestionUsageForSession(sessionId).reduce((sum, row) => sum + usageRowCostUsd(row), 0);
}
function usageTokenSource(meta) {
  return meta.token_source || meta.usage_capture || '-';
}
function billingBadge(label, cls) {
  const colors = {
    billable: ['rgba(22,163,74,.10)', 'var(--green)'],
    cached: ['rgba(37,99,235,.10)', 'var(--blue)'],
    non_billable: ['rgba(107,114,128,.12)', 'var(--muted)']
  };
  const c = colors[cls] || colors.non_billable;
  return `<span style="display:inline-block;font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;background:${c[0]};color:${c[1]};white-space:nowrap">${label}</span>`;
}
function renderSessionProviderUsage(sessionId) {
  const rows = nonIngestionUsageForSession(sessionId);
  if(!rows.length) {
    return `<div style="margin:8px 0 12px;padding:10px;border:1px solid var(--border);border-radius:6px;background:#fff;color:var(--muted);font-size:12px">
      No provider usage rows were recorded for this session.
    </div>`;
  }
  const totals = rows.reduce((acc, r) => {
    const meta = parseMeta(r.request_metadata);
    const cache = getCacheTokens(meta);
    acc.prompt += r.prompt_tokens || 0;
    acc.billablePrompt += Math.max(0, (r.prompt_tokens || 0) - cache.read);
    acc.completion += r.completion_tokens || 0;
    acc.total += r.total_tokens || 0;
    acc.cacheRead += cache.read;
    acc.cacheWrite += cache.write;
    return acc;
  }, {prompt:0, billablePrompt:0, completion:0, total:0, cacheRead:0, cacheWrite:0});
  const sessionMsgs = (RAW.chat_messages || [])
    .filter(m => m.session_id === sessionId)
    .sort((a,b) => (a.created_at||'').localeCompare(b.created_at||''));
  const sessionTurns = buildSessionTurns(sessionMsgs);
  return `<div style="margin:8px 0 12px;border:1px solid var(--border);border-radius:6px;overflow:hidden;background:#fff">
    <div style="padding:8px 10px;background:rgba(22,163,74,.08);border-bottom:1px solid var(--border)">
      <div style="font-size:12px;font-weight:700;color:var(--green)">Provider Billing Ledger</div>
      <div style="font-size:11px;color:var(--muted);margin-top:3px">
        Each row is one provider-billed turn in this session. Input Chars opens the stored user-side input text and Response Chars opens the stored bot-side response text.
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:6px;font-size:11px">
        <span><b>Provider prompt:</b> ${fmt(totals.prompt)}</span>
        <span><b>Billable prompt:</b> ${fmt(totals.billablePrompt)} ${billingBadge('billable','billable')}</span>
        <span><b>Completion:</b> ${fmt(totals.completion)} ${billingBadge('billable','billable')}</span>
        <span><b>Total:</b> ${fmt(totals.total)}</span>
        <span><b>Cache read:</b> ${fmt(totals.cacheRead)} ${billingBadge('cached','cached')}</span>
        <span><b>Cache write:</b> ${fmt(totals.cacheWrite)} ${billingBadge('cached','cached')}</span>
      </div>
    </div>
    <table class="bd-table" style="margin:0">
      <thead><tr>
        <th>Turn</th><th>Date</th><th>User Msg ID</th><th>Bot Msg ID</th>
        <th style="text-align:right">Input Tokens</th><th style="text-align:right">Billable Input</th><th style="text-align:right">Output Tokens</th><th style="text-align:right">Total</th>
        <th style="text-align:right">Cache Read</th><th style="text-align:right">Cache Write</th>
        <th style="text-align:right">Input Chars</th><th style="text-align:right">Response Chars</th><th style="text-align:right">Price</th>
      </tr></thead>
      <tbody>
        ${rows.map((r, idx) => {
          const meta = parseMeta(r.request_metadata);
          const cache = getCacheTokens(meta);
          const billablePrompt = Math.max(0, (r.prompt_tokens || 0) - cache.read);
          const turn = sessionTurns[idx] || { userMsg: null, responseMsgs: [] };
          const userMsg = turn.userMsg || null;
          const responseMsgs = turn.responseMsgs || [];
          const turnSteps = userMsg ? runStepsForTurn(sessionId, userMsg.id) : [];
          const inputText = formatRunStepContent(turnSteps, 'model_request');
          const responseText = formatRunStepContent(turnSteps, 'model_response');
          const inputPopupText = [
            `Session ID: ${sessionId}`,
            `Turn: ${idx + 1}`,
            `User Message ID: ${userMsg?.id || '-'}`,
            `Bot Message IDs: ${responseMsgs.map(msg => msg.id).join(', ') || '-'}`,
            `Date: ${fmtDateTime(r.created_at)}`,
            `Provider: ${r.provider || '-'}`,
            `Model: ${r.model || '-'}`,
            `Input Tokens: ${fmt(r.prompt_tokens)}`,
            `Billable Input Tokens: ${fmt(billablePrompt)}`,
            `Cache Read Tokens: ${fmt(cache.read)}`,
            `Cache Write Tokens: ${fmt(cache.write)}`,
            '',
            'Captured input text:',
            inputText || 'No input text captured.',
          ].join('\\n');
          const responsePopupText = [
            `Session ID: ${sessionId}`,
            `Turn: ${idx + 1}`,
            `User Message ID: ${userMsg?.id || '-'}`,
            `Bot Message IDs: ${responseMsgs.map(msg => msg.id).join(', ') || '-'}`,
            `Date: ${fmtDateTime(r.created_at)}`,
            `Provider: ${r.provider || '-'}`,
            `Model: ${r.model || '-'}`,
            `Output Tokens: ${fmt(r.completion_tokens)}`,
            '',
            'Captured response text:',
            responseText || 'No response text captured.',
          ].join('\\n');
          return `<tr>
            <td class="bd-label">Turn ${idx + 1}</td>
            <td>${fmtDateTime(r.created_at)}</td>
            <td class="mono" title="${escHtml(userMsg?.id || '')}">${escHtml(userMsg?.id || '-')}</td>
            <td class="mono" title="${escHtml(responseMsgs.map(msg => msg.id).join(', ') || '')}">${escHtml(responseMsgs.map(msg => msg.id).join(', ') || '-')}</td>
            <td class="bd-num">${fmt(r.prompt_tokens)}</td>
            <td class="bd-num">${fmt(billablePrompt)}</td>
            <td class="bd-num">${fmt(r.completion_tokens)}</td>
            <td class="bd-num">${fmt(r.total_tokens)}</td>
            <td class="bd-num">${fmt(cache.read)}</td>
            <td class="bd-num">${fmt(cache.write)}</td>
            <td class="bd-num">${popupNumber(payloadChars(meta), 'Provider Input Text', inputText)}</td>
            <td class="bd-num">${popupNumber(meta.response_char_count || (responseText || '').length, 'Provider Response Text', responseText)}</td>
            <td class="bd-num">${fmtUsd(usageRowCostUsd(r))}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
  </div>`;
}
function renderPayloadText(meta) {
  const chunks = payloadTextChunks(meta);
  if(!chunks.length) {
    const keys = Object.keys(meta || {}).sort();
    const hint = keys.length
      ? `Metadata keys present: ${keys.map(escHtml).join(', ')}`
      : 'No request metadata was stored with this usage row.';
    return `<span style="color:var(--muted)">No text payload captured for this row. This usually means the row was recorded before text capture was deployed, by a worker still running older code, or by a non-text request.</span><div style="font-size:11px;color:var(--muted);margin-top:6px">${hint}</div>`;
  }
  const truncNote = meta.input_text_truncated ? `<div style="color:var(--orange);font-size:12px;margin-bottom:8px">Text was truncated at ${fmt(meta.input_text_capture_limit_chars||0)} characters for storage safety.</div>` : '';
  return `${truncNote}${chunks.map((chunk, idx) => `
    <div style="margin:8px 0">
      <div style="font-size:11px;color:var(--muted);margin-bottom:4px">Chunk ${idx + 1} · ${fmt((chunk||'').length)} chars · ${fmtBytes(new Blob([chunk||'']).size)}</div>
      <pre style="white-space:pre-wrap;word-break:break-word;background:#fff;border:1px solid var(--border);border-radius:8px;padding:10px;max-height:260px;overflow:auto;font-family:'SF Mono','Fira Code',monospace;font-size:11px;line-height:1.5">${escHtml(chunk)}</pre>
    </div>`).join('')}`;
}
function toggleAllRows(tableId, btn) {
  const table = document.getElementById(tableId);
  const rows = Array.from(table.querySelectorAll('.msg-row'));
  const sessionRows = Array.from(table.querySelectorAll('.session-row'));
  const isExpand = btn.textContent.includes('Expand');
  
  rows.forEach(r => { r.style.display = isExpand ? 'table-row' : 'none'; });
  sessionRows.forEach(sr => { if(isExpand) sr.classList.add('open'); else sr.classList.remove('open'); });
  
  btn.textContent = isExpand ? 'Collapse All' : 'Expand All';
}
async function downloadIngestionCsv(event, buttonEl) {
  event.preventDefault();
  event.stopPropagation();

  const rowEl = buttonEl.closest('tr');
  if (!rowEl) return;

  const rowKind = rowEl.dataset.rowKind || '';
  const documentId = rowEl.dataset.documentId || rowEl.dataset.parentDocumentId || '';
  const documentType = rowEl.dataset.documentType || 'website';
  if (!documentId) return;

  const originalLabel = buttonEl.textContent;
  buttonEl.disabled = true;
  buttonEl.textContent = 'Preparing...';

  try {
    const chunks = await fetchIngestionChunks(documentId, documentType);
    if (rowKind === 'website-parent') {
      const parentWebsite = CURRENT_INGESTION_VIEW.websiteRootsById.get(String(documentId)) || null;
      const childWebsites = CURRENT_INGESTION_VIEW.websiteChildrenByParentId.get(String(documentId)) || [];
      const pageRows = buildWebsitePageRows(documentId, parentWebsite, childWebsites, chunks);
      if (!pageRows.length) {
        window.alert('No child pages were found for this website row.');
        return;
      }
      const rows = pageRows.map(page => ({
        'Parent Source': rowEl.dataset.sourceName || '',
        'Page URL': page.pageUrl || '',
        'Page Title': page.pageTitle || '',
        'Is Root Page': page.isRootPage ? 'yes' : 'no',
        'Page Date': page.createdAt || '',
        'Chunk Count': page.chunkCount || 0,
        'Content Storage Bytes': page.contentStorageBytes || 0,
        'Embedding Storage Bytes': page.embeddingStorageBytes || 0,
        'Embedding Model': page.model || '',
        'Embedding Tokens': page.embeddingTokens || 0,
        'Chars': page.charCount || 0,
        'Words': page.wordCount || 0,
        'Size Bytes': page.sizeBytes || 0,
      }));
      const fileBase = safeFileNameSegment(rowEl.dataset.sourceName || documentId);
      downloadCsvFile(`${fileBase}_pages.csv`, rows);
      return;
    }

    let exportChunks = chunks;
    if (rowKind === 'website-page') {
      const pageKey = rowEl.dataset.pageKey || '';
      exportChunks = chunks.filter(chunk => (normalizeSourceKey(getChunkPageUrl(chunk)) || '__unknown__') === pageKey);
      if (!exportChunks.length) {
        window.alert('No chunks were found for this page row.');
        return;
      }
    } else if (!chunks.length) {
      window.alert('No chunks were found for this row.');
      return;
    }

    const rows = exportChunks.map(chunk => ({
      'Parent Date': rowEl.dataset.parentCreatedAt || '',
      'Source': rowEl.dataset.sourceName || '',
      'Document ID': documentId,
      'Document Type': documentType,
      'Embedding Model': rowEl.dataset.embeddingModel || '',
      'Embedding Tokens': rowEl.dataset.embeddingTokens || '',
      'Page URL': getChunkPageUrl(chunk) || '',
      'Page Title': getChunkPageTitle(chunk) || '',
      'Chunk ID': chunk.id || '',
      'Chunk Index': chunk.chunk_index ?? '',
      'Chunk Row Number': chunk.chunk_row_number ?? '',
      'Chunk Date': chunk.created_at || '',
      'Chars': chunk.char_count ?? '',
      'Words': chunk.word_count ?? '',
      'Size Bytes': chunk.size_bytes ?? '',
      'Content Storage Bytes': chunk.content_storage_bytes ?? '',
      'Embedding Storage Bytes': chunk.embedding_storage_bytes ?? '',
      'Content Storage Pretty': chunk.content_pretty || '',
      'Embedding Pretty': chunk.embedding_pretty || '',
      'Metadata': chunk.metadata == null ? '' : (typeof chunk.metadata === 'string' ? chunk.metadata : JSON.stringify(chunk.metadata)),
      'Content': chunk.content || '',
    }));

    const fileBase = safeFileNameSegment(rowEl.dataset.sourceName || documentId);
    const suffix = rowKind === 'website-page' ? 'page_chunks' : 'chunks';
    downloadCsvFile(`${fileBase}_${suffix}.csv`, rows);
  } catch (error) {
    window.alert('Failed to download the CSV.');
  } finally {
    buttonEl.disabled = false;
    buttonEl.textContent = originalLabel;
  }
}
function removeNestedRowsForParent(parentRow) {
  let next = parentRow.nextElementSibling;
  while(next && (next.classList.contains('page-row') || next.classList.contains('chunk-row'))) {
    const toRemove = next;
    next = next.nextElementSibling;
    toRemove.remove();
  }
}
function removeChunkRowsForPage(pageRow) {
  let next = pageRow.nextElementSibling;
  while(next && next.classList.contains('chunk-row')) {
    const toRemove = next;
    next = next.nextElementSibling;
    toRemove.remove();
  }
}
async function toggleIngestionParentRow(rowEl) {
  const documentId = rowEl.dataset.documentId || '';
  const documentType = rowEl.dataset.documentType || '';
  const rowKind = rowEl.dataset.rowKind || '';
  if (!documentId || !documentType) return;
  const isOpen = rowEl.classList.contains('open');
  const embeddingModel = rowEl.dataset.embeddingModel || '';
  removeNestedRowsForParent(rowEl);

  if (isOpen) {
    rowEl.classList.remove('open');
    return;
  }

  rowEl.classList.add('open');

  const websiteId = String(documentId);
  const websiteChildren = rowKind === 'website-parent'
    ? (CURRENT_INGESTION_VIEW.websiteChildrenByParentId.get(websiteId) || [])
    : [];
  const showWebsitePages = rowKind === 'website-parent' && websiteChildren.length > 0;

  const loadingRow = document.createElement('tr');
  loadingRow.className = showWebsitePages ? 'page-row' : 'chunk-row';
  loadingRow.innerHTML = `<td colspan="13" style="color:var(--muted)">${showWebsitePages ? 'Loading child pages...' : 'Loading chunk rows...'}</td>`;
  rowEl.after(loadingRow);

  try {
    const chunks = await fetchIngestionChunks(documentId, documentType);
    loadingRow.remove();

    if (rowKind === 'website-parent') {
      const parentWebsite = CURRENT_INGESTION_VIEW.websiteRootsById.get(websiteId) || null;
      const childWebsites = websiteChildren;
      if (!childWebsites.length) {
        if (!chunks.length) {
          const emptyRow = document.createElement('tr');
          emptyRow.className = 'chunk-row';
          emptyRow.innerHTML = `<td colspan="13" style="color:var(--muted)">No chunks found for this website.</td>`;
          rowEl.after(emptyRow);
          return;
        }

        let insertAfter = rowEl;
        chunks.forEach(chunk => {
          const chunkRowEl = createChunkRowElement(chunk, embeddingModel);
          insertAfter.after(chunkRowEl);
          insertAfter = chunkRowEl;
        });
        return;
      }

      const pageRows = buildWebsitePageRows(documentId, parentWebsite, childWebsites, chunks);
      if (!pageRows.length) {
        const emptyRow = document.createElement('tr');
        emptyRow.className = 'page-row';
        emptyRow.innerHTML = `<td colspan="13" style="color:var(--muted)">No child pages found for this website.</td>`;
        rowEl.after(emptyRow);
        return;
      }

      let insertAfter = rowEl;
      pageRows.forEach(page => {
        const pageRowEl = createWebsitePageRowElement(page, documentId);
        insertAfter.after(pageRowEl);
        insertAfter = pageRowEl;
      });
      return;
    }

    if (!chunks.length) {
      const emptyRow = document.createElement('tr');
      emptyRow.className = 'chunk-row';
      emptyRow.innerHTML = `<td colspan="13" style="color:var(--muted)">No chunks found for this record.</td>`;
      rowEl.after(emptyRow);
      return;
    }

    let insertAfter = rowEl;
    chunks.forEach(chunk => {
      const chunkRowEl = createChunkRowElement(chunk, embeddingModel);
      insertAfter.after(chunkRowEl);
      insertAfter = chunkRowEl;
    });
  } catch (error) {
    loadingRow.innerHTML = `<td colspan="13" style="color:var(--red)">Failed to load ${rowKind === 'website-parent' ? 'child pages' : 'chunk rows'}.</td>`;
  }
}
async function toggleWebsitePageRow(rowEl) {
  const parentDocumentId = rowEl.dataset.parentDocumentId || '';
  const pageKey = rowEl.dataset.pageKey || '';
  if (!parentDocumentId || !pageKey) return;
  const isOpen = rowEl.classList.contains('open');
  const embeddingModel = rowEl.dataset.embeddingModel || '';
  removeChunkRowsForPage(rowEl);

  if (isOpen) {
    rowEl.classList.remove('open');
    return;
  }

  rowEl.classList.add('open');

  const loadingRow = document.createElement('tr');
  loadingRow.className = 'chunk-row';
  loadingRow.innerHTML = `<td colspan="13" style="color:var(--muted)">Loading chunk rows...</td>`;
  rowEl.after(loadingRow);

  try {
    const chunks = await fetchIngestionChunks(parentDocumentId, 'website');
    const pageChunks = chunks.filter(chunk => (normalizeSourceKey(getChunkPageUrl(chunk)) || '__unknown__') === pageKey);
    loadingRow.remove();

    if (!pageChunks.length) {
      const emptyRow = document.createElement('tr');
      emptyRow.className = 'chunk-row';
      emptyRow.innerHTML = `<td colspan="13" style="color:var(--muted)">No chunks found for this page.</td>`;
      rowEl.after(emptyRow);
      return;
    }

    let insertAfter = rowEl;
    pageChunks.forEach(chunk => {
      const chunkRowEl = createChunkRowElement(chunk, embeddingModel);
      insertAfter.after(chunkRowEl);
      insertAfter = chunkRowEl;
    });
  } catch (error) {
    loadingRow.innerHTML = `<td colspan="13" style="color:var(--red)">Failed to load chunk rows.</td>`;
  }
}
// === SET DAYS ===
function setDays(d) {
  currentDays = d;
  document.querySelectorAll('.toolbar button[id^="btn-"]').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('btn-'+d);
  if(btn) btn.classList.add('active');
  render();
}

// === RENDER ===
function render() {
  const days = currentDays;
  const sessions = filterByDate(RAW.sessions, days);
  const files = filterByDate(RAW.files, days);
  const websites = filterByDate(RAW.websites, days);
  const tokenLog = filterByDate(RAW.token_usage_log||[], days);
  const ingestionTokenLog = tokenLog.filter(isIngestionUsage);
  const { websiteUsageById, fileUsageById } = buildUsageMaps(ingestionTokenLog);
  const { websiteRootsById, websiteChildrenByParentId } = buildWebsiteChildrenMap(websites);
  const fileRowsById = new Map((files || []).map(file => [String(file.id), file]));
  CURRENT_INGESTION_VIEW = {
    websiteUsageById,
    fileUsageById,
    websiteRootsById,
    websiteChildrenByParentId,
    fileRowsById,
  };

  document.getElementById('subtitle').textContent =
    `Last ${days} days \\u00b7 Generated ${new Date().toISOString().replace('T',' ').substring(0,16)} UTC`;

  // === AGGREGATE CALCULATIONS ===
  const totalSessions = sessions.length;
  const totalMsgs = sessions.reduce((a,r) => a+(r.message_count||0), 0);
  const totalPromptTokens = sessions.reduce((a,r) => a+(r.total_prompt_token_count||0), 0);
  const totalCompletionTokens = sessions.reduce((a,r) => a+(r.total_completion_token_count||0), 0);
  const totalMsgTokens = sessions.reduce((a,r) => a+(r.total_message_token_count||0), 0);
  const totalChars = sessions.reduce((a,r) => a+(r.total_character_count||0), 0);
  const totalFiles = files.length;
  const fileTokens = files.reduce((a,r) => a+(r.embedding_token_count||0), 0);
  const fileSizeBytes = files.reduce((a,r) => a+(r.file_size||0), 0);
  const totalWebsites = websites.length;
  const rootWebsiteRows = websites.filter(w => !w.parent_id);
  const childWebpageRows = websites.filter(w => !!w.parent_id);
  const totalWebsiteRoots = rootWebsiteRows.length;
  const totalWebpagesScraped = childWebpageRows.length;
  const webTokens = websites.reduce((a,r) => a+(r.embedding_token_count||0), 0);
  const websiteSizeBytes = websites.reduce((a,r) => a+(r.file_size||0), 0);

  // Token log cache totals
  let totalCacheReadTokens = 0, totalCacheWriteTokens = 0;
  tokenLog.forEach(r => {
    const c = getCacheTokens(r.request_metadata);
    totalCacheReadTokens += c.read;
    totalCacheWriteTokens += c.write;
  });

  const ingestionTokens = ingestionTokenLog.reduce((a,r) => a + (r.total_tokens||0), 0);
  const ingestionPriceUsd = ingestionTokenLog.reduce(
    (sum, row) => sum + estimatedEmbeddingCostUsd(row.model || '', row.total_tokens || row.prompt_tokens || 0),
    0
  );
  const ingestionModels = Array.from(new Set(ingestionTokenLog.map(r => String(r.model || '')).filter(Boolean)));
  const primaryIngestionModel = ingestionModels[0] || 'text-embedding-3-small';
  const chatUsageRows = tokenLog.filter(r => !isIngestionUsage(r));
  const chatModels = Array.from(new Set(chatUsageRows.map(r => String(r.model || '')).filter(Boolean)));
  const primaryChatModel = chatModels.find(model => String(model).toLowerCase().includes('2.5-flash-lite'))
    || chatModels[0]
    || 'gemini-2.5-flash-lite';

  // === KNOWLEDGE BASE INGESTION SUMMARY ===
  document.getElementById('token-summary').innerHTML = `
    <h2>Knowledge Base Ingestion Summary</h2>
    <div class="token-grid">
      <div class="token-item">
        <div class="token-label">Embedding Tokens</div>
        <div class="token-value">${fmt(ingestionTokens)}</div>
        <div class="token-detail">Total embedding tokens from knowledge ingestion</div>
      </div>
      <div class="token-item">
        <div class="token-label">Files Uploaded</div>
        <div class="token-value" style="font-size:20px">${fmt(totalFiles)}</div>
        <div class="token-detail">${fmtBytes(fileSizeBytes)} total uploaded file size</div>
      </div>
      <div class="token-item">
        <div class="token-label">Websites Scraped</div>
        <div class="token-value" style="font-size:20px">${fmt(totalWebsiteRoots)}</div>
        <div class="token-detail">Root website scrape entries</div>
      </div>
      <div class="token-item">
        <div class="token-label">WebPages Scraped</div>
        <div class="token-value" style="font-size:20px">${fmt(totalWebpagesScraped)}</div>
        <div class="token-detail">${fmtBytes(websiteSizeBytes)} total scraped web content size</div>
      </div>
      <div class="token-item">
        <div class="token-label">Total Cost</div>
        <div class="token-value" style="font-size:20px">${fmtUsd(ingestionPriceUsd)}</div>
        <div class="token-detail">Estimated total embedding cost</div>
      </div>
      <div class="token-item">
        <div class="token-label">Unit Rate</div>
        <div class="token-value" style="font-size:16px">${escHtml(primaryIngestionModel)}</div>
        <div class="token-detail">${escHtml(ingestionUnitRateLabel(primaryIngestionModel))}</div>
      </div>
    </div>
  `;

  // === CHAT SUMMARY ===
  document.getElementById('kpis').innerHTML = `
    <div class="token-summary">
      <h2>Chat Summary</h2>
      <div class="kpi-grid">
        <div class="kpi"><div class="label">Total Sessions</div><div class="value accent">${fmt(totalSessions)}</div><div class="sub">${fmt(totalMsgs)} messages total</div></div>
        <div class="kpi"><div class="label">Total Tokens</div><div class="value green">${fmt(totalPromptTokens + totalCompletionTokens)}</div><div class="sub">Input plus output chat tokens</div></div>
        <div class="kpi"><div class="label">Input Tokens</div><div class="value cyan">${fmt(totalPromptTokens)}</div><div class="sub">Prompt tokens returned by provider usage</div></div>
        <div class="kpi"><div class="label">Output Tokens</div><div class="value accent2">${fmt(totalCompletionTokens)}</div><div class="sub">Completion tokens from chat sessions</div></div>
        <div class="kpi"><div class="label">Unit Rate</div><div class="value" style="font-size:18px">${escHtml(primaryChatModel)}</div><div class="sub">${escHtml(chatUnitRateLabel(primaryChatModel))}</div></div>
      </div>
    </div>
  `;

  // === INSIGHTS ===
  document.getElementById('usage-insights').innerHTML = '';

  // === HELPERS FOR MESSAGES ===
  const chatMsgs = filterByDate(RAW.chat_messages||[], days);
  const roleName = r => r==='assistant'?'Bot':r==='user'?'User':r==='human_agent'?'Human Agent':(r||'Unknown');

  // Group messages by session_id
  const msgBySession = {};
  chatMsgs.forEach(m => {
    if(!msgBySession[m.session_id]) msgBySession[m.session_id] = [];
    msgBySession[m.session_id].push(m);
  });
  Object.values(msgBySession).forEach(arr => arr.sort((a,b) => (a.created_at||'').localeCompare(b.created_at||'')));

  // === SESSIONS TABLE ===
  const sessionsEl = document.getElementById('sessions-table');
  sessionsEl.innerHTML = '';
  sessions.slice(0,100).forEach(r => {
    const sessionRow = document.createElement('tr');
    sessionRow.className = 'session-row';
    sessionRow.dataset.sessionId = r.id;
    sessionRow.setAttribute('onclick', `toggleSession(this, '${r.id}')`);
    const sessionPrice = sessionPriceUsd(r.id);
    sessionRow.innerHTML = `
      <td class="mono">${r.id}</td>
      <td>${fmtDateTime(r.started_at)}</td><td>${r.message_count||0}</td>
      <td class="token-cell">${fmt(r.total_prompt_token_count)}</td>
      <td class="token-cell">${fmt(r.total_completion_token_count)}</td>
      <td class="token-cell">${fmt((r.total_system_prompt_token_count||0)+(r.total_history_token_count||0)+(r.total_tool_def_token_count||0))}</td>
      <td class="token-cell">${fmt((r.total_user_msg_token_count||0)+(r.total_bot_response_token_count||0))}</td>
      <td>${badge(r.archive_status)}</td>
      <td>${fmtUsd(sessionPrice)}</td>`;
    sessionsEl.appendChild(sessionRow);
  });

  // === KNOWLEDGE INGESTION TABLE ===
  const parentRows = buildIngestionParentRows(files, websites);
  document.getElementById('token-log-table').innerHTML = parentRows
    .slice(0, 300)
    .map(renderIngestionParentRow)
    .join('');
}

// === RENDER AGENT RUN STEPS FOR A USER MESSAGE ===
function renderRunSteps(userMsgId, sessionId) {
  const steps = (RAW.run_steps||[]).filter(s => s.user_message_id === userMsgId);
  if(steps.length === 0) return '';
  const partLabel = p => ({
    'system_prompt':'System Prompt','user_prompt':'User Prompt','text':'Text Response',
    'tool_call':'Tool Call','tool_return':'Tool Return','thinking':'Thinking'
  }[p]||p);
  const partColor = p => ({
    'system_prompt':'var(--accent)','user_prompt':'var(--blue)','text':'var(--green)',
    'tool_call':'var(--orange)','tool_return':'var(--cyan)','thinking':'var(--accent2)'
  }[p]||'var(--muted)');
  const totalTokens = steps.reduce((a,s) => a + (s.token_count||0), 0);
  let html = `<div style="margin-top:8px;border:1px solid var(--border);border-radius:6px;overflow:hidden">
    <div style="background:rgba(79,70,229,.08);padding:6px 10px;font-size:11px;font-weight:600;color:var(--accent);cursor:pointer" onclick="const t=this.nextElementSibling;t.style.display=t.style.display==='none'?'':'none'">
      Agent Run Steps (${steps.length} steps, ${fmt(totalTokens)} diagnostic tokens) ${billingBadge('non-billable diagnostics','non_billable')} [show/hide]
      <div style="font-weight:400;color:var(--muted);margin-top:2px">Step tokens are counted from captured request/response parts. They are non-billable diagnostics, not the provider-billed total.</div>
    </div>
    <div style="display:none">
    <table class="bd-table" style="margin:0">
      <thead><tr><th>#</th><th>Direction</th><th>Part Type</th><th>Tool</th><th style="text-align:right">Tokens</th><th style="text-align:right">Words</th><th style="text-align:right">Chars</th><th>Billing</th><th>Source</th><th>Full Captured Content (click to expand)</th></tr></thead>
      <tbody>`;
  steps.forEach(s => {
    const stepContent = s.content_full || s.content_preview || '';
    html += `<tr>
      <td style="font-weight:600">${s.step_number}</td>
      <td><span style="font-size:10px;padding:2px 6px;border-radius:4px;background:${s.step_type==='model_request'?'rgba(37,99,235,.1)':'rgba(22,163,74,.1)'};color:${s.step_type==='model_request'?'var(--blue)':'var(--green)'}">${s.step_type==='model_request'?'INPUT':'OUTPUT'}</span></td>
      <td style="color:${partColor(s.part_type)};font-weight:600">${partLabel(s.part_type)}</td>
      <td style="font-size:11px">${s.tool_name||'-'}</td>
      <td class="bd-num">${fmt(s.token_count)}</td>
      <td class="bd-num">${fmt(s.word_count)}</td>
      <td class="bd-num">${fmt(s.char_count)}</td>
      <td>${billingBadge('non-billable','non_billable')}</td>
      <td style="font-size:10px;color:var(--muted)">${escHtml(s.token_source||'captured_content')}</td>
      <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(stepContent)}</div></td>
    </tr>`;
  });
  html += `</tbody></table></div></div>`;
  return html;
}

function runStepsForTurn(sessionId, userMessageId) {
  return (RAW.run_steps || [])
    .filter(step => step.session_id === sessionId && step.user_message_id === userMessageId)
    .sort((a, b) => Number(a.step_number || 0) - Number(b.step_number || 0));
}

function formatRunStepContent(steps, targetStepType) {
  const filtered = (steps || []).filter(step => String(step.step_type || '').toLowerCase() === targetStepType);
  if(!filtered.length) return '';
  return filtered.map(step => {
    const label = String(step.part_type || 'content').replace(/_/g, ' ');
    const body = step.content_full || step.content_preview || '';
    return `[${label}]\n${body}`;
  }).join('\n\n');
}

function buildSessionTurns(msgs) {
  const turns = [];
  let currentTurn = null;

  (msgs || []).forEach(msg => {
    const role = String(msg.role || '').toLowerCase();
    if(role === 'user') {
      currentTurn = {
        userMsg: msg,
        responseMsgs: [],
      };
      turns.push(currentTurn);
      return;
    }

    if(!currentTurn) {
      currentTurn = {
        userMsg: null,
        responseMsgs: [],
      };
      turns.push(currentTurn);
    }

    currentTurn.responseMsgs.push(msg);
  });

  return turns;
}

// === EXPAND/COLLAPSE SESSION MESSAGES ===
function toggleSession(rowEl, sessionId) {
  const isOpen = rowEl.classList.contains('open');

  let next = rowEl.nextElementSibling;
  while(next && next.classList.contains('msg-row')) {
    const toRemove = next;
    next = next.nextElementSibling;
    toRemove.remove();
  }

  if(isOpen) {
    rowEl.classList.remove('open');
    return;
  }

  rowEl.classList.add('open');

  let insertAfter = rowEl;
  const providerRow = document.createElement('tr');
  providerRow.className = 'msg-row';
  providerRow.innerHTML = `<td colspan="9" style="padding-left:24px">${renderSessionProviderUsage(sessionId)}</td>`;
  insertAfter.after(providerRow);
}

// === EXCEL DOWNLOAD (multi-sheet XLSX via SheetJS) ===
function downloadExcel() {
  const days = currentDays;
  const sessions = filterByDate(RAW.sessions, days);
  const chatMsgs = filterByDate(RAW.chat_messages||[], days);
  const tokenLog = filterByDate(RAW.token_usage_log||[], days);
  const ingestionTokenLog = tokenLog.filter(isIngestionUsage);

  const wb = XLSX.utils.book_new();

  function styleWorksheet(ws, opts={}) {
    if(!ws || !ws['!ref']) return ws;
    const range = XLSX.utils.decode_range(ws['!ref']);
    ws['!autofilter'] = { ref: ws['!ref'] };
    ws['!freeze'] = { xSplit: 0, ySplit: opts.freezeRows || 1 };

    for(let row = range.s.r; row <= range.e.r; row += 1) {
      for(let col = range.s.c; col <= range.e.c; col += 1) {
        const cellRef = XLSX.utils.encode_cell({ r: row, c: col });
        const cell = ws[cellRef];
        if(!cell) continue;
        cell.s = cell.s || {};
        cell.s.alignment = Object.assign({}, cell.s.alignment || {}, {
          wrapText: false,
          vertical: 'top',
        });
      }
    }

    return ws;
  }

  function appendTotalsRow(ws, totalsByHeader) {
    if(!ws || !ws['!ref'] || !totalsByHeader || !Object.keys(totalsByHeader).length) return ws;
    const range = XLSX.utils.decode_range(ws['!ref']);
    const headers = [];
    for(let col = range.s.c; col <= range.e.c; col += 1) {
      const cellRef = XLSX.utils.encode_cell({ r: range.s.r, c: col });
      headers.push(String(ws[cellRef]?.v || ''));
    }

    const footer = headers.map((header, idx) => {
      if(idx === 0) return 'TOTALS';
      return Object.prototype.hasOwnProperty.call(totalsByHeader, header) ? totalsByHeader[header] : '';
    });
    XLSX.utils.sheet_add_aoa(ws, [footer], { origin: -1 });
    return ws;
  }

  // Sheet 1: Chat Sessions
  const sessData = sessions.map(r => {
    return {
      'Session ID': r.id,
      'Started At': r.started_at,
      'Messages': r.message_count||0,
      'Prompt Tokens (input)': r.total_prompt_token_count||0,
      'Completion Tokens (output)': r.total_completion_token_count||0,
      'Context Tokens': (r.total_system_prompt_token_count||0)+(r.total_history_token_count||0)+(r.total_tool_def_token_count||0),
      'Message Text Tokens': (r.total_user_msg_token_count||0)+(r.total_bot_response_token_count||0),
      'Status': r.archive_status||''
    };
  });
  const sessSheet = XLSX.utils.json_to_sheet(sessData);
  styleWorksheet(sessSheet);
  XLSX.utils.book_append_sheet(wb, sessSheet, 'Chat Sessions');

  // Sheet 2: Chat Messages
  const msgData = chatMsgs.map(r => {
    return {
      'Message ID': r.id,
      'Session ID': r.session_id,
      'Role': r.role==='assistant'?'Bot':r.role==='user'?'User':r.role,
      'Prompt Tokens': r.prompt_token_count||0,
      'Completion Tokens': r.completion_token_count||0,
      'System Prompt Tokens': r.system_prompt_token_count||0,
      'History Tokens': r.history_token_count||0,
      'Tool Def Tokens': r.tool_def_token_count||0,
      'User Msg Tokens': r.user_msg_token_count||0,
      'Bot Response Tokens': r.bot_response_token_count||0,
      'Created': r.created_at||'',
      'Message Preview': trunc(r.content||'', 240)
    };
  });
  const msgSheet = XLSX.utils.json_to_sheet(msgData);
  styleWorksheet(msgSheet);
  XLSX.utils.book_append_sheet(wb, msgSheet, 'Chat Messages');

  // Sheet 3: Agent Run Steps
  const stepsData = (RAW.run_steps||[]).map(r => ({
    'Session ID': r.session_id,
    'User Message ID': r.user_message_id||'',
    'Step #': r.step_number,
    'Direction': r.step_type==='model_request'?'INPUT':'OUTPUT',
    'Part Type': r.part_type,
    'Tool Name': r.tool_name||'',
    'Tokens': r.token_count||0,
    'Words': r.word_count||0,
    'Chars': r.char_count||0,
    'Content Preview': r.content_preview||'',
    'Created': r.created_at||''
  }));
  const stepsSheet = XLSX.utils.json_to_sheet(stepsData);
  styleWorksheet(stepsSheet);
  XLSX.utils.book_append_sheet(wb, stepsSheet, 'Agent Run Steps');

  // Sheet 4: Knowledge Ingestion
  const tokenLogData = ingestionTokenLog.map(r => {
    const meta = parseMeta(r.request_metadata);
    return {
      'Created': r.created_at||'',
      'Provider': r.provider||'',
      'Model': r.model||'',
      'Source': strictIngestionSource(meta),
      'Embedding Tokens': r.total_tokens || r.prompt_tokens || 0,
      'Input Characters': payloadChars(meta),
      'Input Words': payloadWords(meta),
      'Input Size Bytes': payloadBytes(meta),
      'Size Pretty': fmtBytes(payloadBytes(meta)),
      'Input Text Chunks': payloadTextChunks(meta).join('\\n\\n--- chunk ---\\n\\n'),
      'Input Text Truncated': meta.input_text_truncated ? 'yes' : 'no',
      'Tool Calls': meta.tool_call_count||0,
      'Token Source': meta.token_source||''
    };
  });
  const ingestionSheet = XLSX.utils.json_to_sheet(tokenLogData);
  appendTotalsRow(ingestionSheet, {
    'Input Characters': ingestionTokenLog.reduce((sum, row) => sum + payloadChars(parseMeta(row.request_metadata)), 0),
    'Input Words': ingestionTokenLog.reduce((sum, row) => sum + payloadWords(parseMeta(row.request_metadata)), 0),
    'Input Size Bytes': ingestionTokenLog.reduce((sum, row) => sum + payloadBytes(parseMeta(row.request_metadata)), 0),
    'Size Pretty': fmtBytes(ingestionTokenLog.reduce((sum, row) => sum + payloadBytes(parseMeta(row.request_metadata)), 0)),
  });
  styleWorksheet(ingestionSheet);
  XLSX.utils.book_append_sheet(wb, ingestionSheet, 'Knowledge Ingestion');

  // Sheet 5: Usage By Call Type
  const groupedUsageData = groupByCallType(ingestionTokenLog).map(g => ({
    'Call Type': callTypeLabel(g.call_type),
    'Raw Call Type': g.call_type,
    'Requests': g.requests,
    'Embedding Tokens': g.total || g.prompt,
    'Tool Calls': g.tools
  }));
  const groupedUsageSheet = XLSX.utils.json_to_sheet(groupedUsageData);
  styleWorksheet(groupedUsageSheet);
  XLSX.utils.book_append_sheet(wb, groupedUsageSheet, 'Usage By Call Type');

  // Sheet 6: Largest Token Calls
  const topCallsData = [...ingestionTokenLog].sort((a,b) => (b.total_tokens||0) - (a.total_tokens||0)).slice(0,100).map(r => {
    const meta = parseMeta(r.request_metadata);
    return {
      'Created': r.created_at||'',
      'Source': strictIngestionSource(meta),
      'Provider': r.provider||'',
      'Model': r.model||'',
      'Embedding Tokens': r.total_tokens || r.prompt_tokens || 0,
      'Token Source': meta.token_source||''
    };
  });
  const topCallsSheet = XLSX.utils.json_to_sheet(topCallsData);
  styleWorksheet(topCallsSheet);
  XLSX.utils.book_append_sheet(wb, topCallsSheet, 'Largest Token Calls');

  XLSX.writeFile(wb, `usage-report-${days}d-${new Date().toISOString().substring(0,10)}.xlsx`);
}


// === INIT ===
currentTenant = getTenantFromUrl();
console.log('currentTenant from URL:', currentTenant);
initTenantFilter();
if (currentTenant) {
  document.getElementById('tenant-filter').value = currentTenant;
}
document.addEventListener('click', closeHeaderTooltip);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeHeaderTooltip(); });
window.addEventListener('resize', closeHeaderTooltip);
window.addEventListener('scroll', closeHeaderTooltip, true);
document.getElementById('header-tooltip-popover').addEventListener('click', e => e.stopPropagation());
console.log('Sessions in RAW:', RAW.sessions ? RAW.sessions.length : 0);
render();
</script>
</body>
</html>"""
    )

    return HTMLResponse(content=html)
