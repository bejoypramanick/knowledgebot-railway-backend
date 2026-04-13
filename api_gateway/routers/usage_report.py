"""
Usage Report - Single Endpoint
GET /reports/usage → self-contained HTML report.
All filtering and Excel download handled client-side.
Protected by session auth middleware.
"""

import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
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
        elif hasattr(v, '__str__') and not isinstance(v, (int, float, bool, str, type(None))):
            d[k] = str(v)
    return d


async def _fetch_all_data():
    """Fetch 365 days of data. JS will filter client-side."""
    since = datetime.utcnow() - timedelta(days=365)

    async with get_db_session() as db:
        sessions = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT id, started_at, last_activity_at, message_count,
                   total_character_count, total_word_count, total_token_count,
                   total_message_token_count, total_prompt_token_count, total_completion_token_count,
                   total_system_prompt_token_count, total_history_token_count,
                   total_tool_def_token_count, total_user_msg_token_count, total_bot_response_token_count,
                   archive_status, sentiment, duration_minutes, created_at
            FROM chat_sessions WHERE created_at >= :since ORDER BY created_at DESC
        """), {"since": since})).fetchall()]

        files = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT id, original_filename, display_name, file_extension, processing_status,
                   file_size, char_count,
                   filestore_character_count, filestore_word_count, filestore_token_count,
                   processed_by_extractor, created_at
            FROM file_uploads WHERE created_at >= :since ORDER BY created_at DESC
        """), {"since": since})).fetchall()]

        websites = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT id, original_url, title, processing_status, pages_scraped,
                   file_size, char_count,
                   filestore_character_count, filestore_word_count, filestore_token_count,
                   parent_id, depth, created_at
            FROM scraped_websites WHERE created_at >= :since ORDER BY created_at DESC
        """), {"since": since})).fetchall()]

        chat_messages = [_row_to_dict(r) for r in (await db.execute(text("""
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
            ORDER BY cm.created_at DESC
        """), {"since": since})).fetchall()]

        run_steps = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT id, session_id, user_message_id, step_number, step_type, part_type,
                   tool_name, content_preview, char_count, word_count, token_count, created_at
            FROM agent_run_steps
            WHERE created_at >= :since
            ORDER BY session_id, user_message_id, step_number
        """), {"since": since})).fetchall()]

        token_usage_log = []
        rows = (await db.execute(text("""
            SELECT id, session_id, message_id, provider, model,
                   prompt_tokens, completion_tokens, total_tokens,
                   api_call_type, request_metadata, created_at
            FROM token_usage_log
            WHERE created_at >= :since
            ORDER BY created_at DESC
        """), {"since": since})).fetchall()
        
        for r in rows:
            d = _row_to_dict(r)
            meta = d.get('request_metadata')
            if meta and isinstance(meta, str):
                try:
                    # Fallback if DB driver returned a string for JSONB
                    d['request_metadata'] = json.loads(meta)
                    logger.debug(f"Parsed metadata string for row {d['id']}")
                except:
                    pass
            token_usage_log.append(d)

    logger.info(f"Report data fetched: {len(token_usage_log)} usage rows")
    if token_usage_log:
        first_meta = token_usage_log[0].get('request_metadata')
        logger.info(f"Sample metadata type: {type(first_meta)} value: {str(first_meta)[:100]}")

    return {
        "sessions": sessions, "files": files,
        "websites": websites, "chat_messages": chat_messages,
        "run_steps": run_steps, "token_usage_log": token_usage_log
    }


@router.get("/usage", response_class=HTMLResponse)
async def usage_report(request: Request):
    """Single endpoint. All data embedded, JS handles filtering/downloads."""
    data = await _fetch_all_data()
    data_json = json.dumps(data, default=str)

    html = """<!DOCTYPE html>
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
.legend{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:32px;font-size:13px;line-height:1.8}
.legend h3{font-size:15px;margin-bottom:12px;color:var(--text)}
.legend-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(400px,1fr));gap:16px}
.legend-section{padding:8px 0}
.legend-section h4{font-size:12px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);margin-bottom:8px}
.legend dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px}
.legend dt{font-weight:600;color:var(--accent);white-space:nowrap}
.legend dd{color:var(--text);margin:0}
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
.metadata-snippet{font-family:'SF Mono','Fira Code',monospace;font-size:10px;color:var(--muted);max-width:320px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hidden-panel{display:none}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px;margin-bottom:32px}
.chart-card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px}
.chart-card h3{font-size:15px;margin-bottom:12px}
.bar-row{display:grid;grid-template-columns:minmax(100px,150px) 1fr auto;gap:10px;align-items:center;margin:9px 0;font-size:12px}
.bar-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--text)}
.bar-track{height:12px;background:#e9ecef;border-radius:6px;overflow:hidden}
.bar-fill{height:100%;background:var(--accent);border-radius:6px;min-width:2px}
.bar-fill.green{background:var(--green)}.bar-fill.orange{background:var(--orange)}.bar-fill.cyan{background:var(--cyan)}.bar-fill.red{background:var(--red)}
.bar-value{font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap}
@media (max-width: 760px) {
  body{padding:12px}
  h1{font-size:24px}
  .subtitle{margin-bottom:16px}
  .toolbar{gap:8px;margin-bottom:18px}
  .toolbar button{flex:1 1 calc(50% - 8px);padding:10px 8px}
  .toolbar span{display:none}
  .summary-actions button{flex:1 1 100%;padding:12px}
  .kpi-grid,.token-grid,.insight-grid,.chart-grid{grid-template-columns:1fr;gap:12px;margin-bottom:20px}
  .kpi,.token-summary,.insight,.chart-card,.legend{padding:14px;border-radius:8px}
  .kpi .value{font-size:24px}
  .token-item .token-value{font-size:22px}
  .section h2{font-size:17px}
  .legend-grid{grid-template-columns:1fr}
  .legend dl{grid-template-columns:1fr}
  .table-wrap{max-height:420px}
  table{font-size:12px}
  th,td{padding:8px}
  .bar-row{grid-template-columns:1fr;gap:5px}
  .bar-value{font-size:11px}
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
  <button onclick="setDays(30)" id="btn-30" class="active">30 Days</button>
  <button onclick="setDays(90)" id="btn-90">90 Days</button>
  <button onclick="setDays(180)" id="btn-180">180 Days</button>
  <button onclick="setDays(365)" id="btn-365">All Time</button>
  <span style="flex:1"></span>
  <button onclick="downloadExcel()">Download Excel</button>
</div>

<div class="legend" id="legend-panel">
<h3>Report Notes <span style="font-size:12px;color:var(--muted);font-weight:400;cursor:pointer" onclick="document.getElementById('legend-detail').style.display=document.getElementById('legend-detail').style.display==='none'?'block':'none'">[show/hide]</span></h3>
<div id="legend-detail" class="legend-grid" style="display:none">
  <div class="legend-section">
    <h4>What is Included</h4>
    <dl>
      <dt>Chat</dt><dd>Prompt, completion, cache read/write, tool calls, and per-session totals</dd>
      <dt>Knowledge ingestion</dt><dd>Indexed content token counts and table-formatting model calls</dd>
      <dt>Other API calls</dt><dd>Embeddings, Gemini Vision equation extraction, and cache creation</dd>
    </dl>
  </div>
</div>
</div>

<!-- Token Summary -->
<div class="token-summary" id="token-summary"></div>

<div class="kpi-grid" id="kpis"></div>

<div class="insight-grid" id="usage-insights"></div>

<div class="summary-actions">
  <button onclick="togglePanel('details-panel','details-toggle')" id="details-toggle">Show details</button>
  <button class="secondary" onclick="togglePanel('charts-panel','charts-toggle')" id="charts-toggle">Show charts</button>
  <button class="secondary" onclick="downloadExcel()">Download Excel</button>
</div>

<div id="charts-panel" class="hidden-panel">
  <div class="section"><h2>Charts</h2><div class="chart-grid" id="charts-grid"></div></div>
</div>

<div id="details-panel" class="hidden-panel">
<div class="section"><h2>Chat Sessions <span style="font-size:13px;color:var(--muted);font-weight:400">(click to expand messages)</span></h2><div class="table-wrap" style="max-height:700px"><table>
  <thead><tr><th>Session ID</th><th>Started</th><th title="Total messages in this session">Msgs</th><th title="Input tokens">Prompt Tokens</th><th title="Output tokens">Completion Tokens</th><th title="System prompt + history + tool overhead">Context Tokens</th><th title="Current user + bot message text tokens">Message Tokens</th><th>Status</th></tr></thead>
  <tbody id="sessions-table"></tbody>
</table></div></div>

<div class="section"><h2>API Token Usage Log <span style="font-size:13px;color:var(--muted);font-weight:400">(provider usage per request)</span></h2><div class="table-wrap"><table>
  <thead><tr><th>Date</th><th>Call Type</th><th>Model</th><th>Total Tok</th><th>Prompt</th><th>Output</th><th>Cache</th><th>Chars</th><th>Words</th><th>Size</th><th>Source</th><th>Context</th></tr></thead>
  <tbody id="token-log-table"></tbody>
</table></div></div>
</div>

</div>

<script>
// === DATA ===
const RAW = """ + data_json + """;
let currentDays = 30;

// === HELPERS ===
const fmt = n => (n||0).toLocaleString();
const fmtDate = s => s ? new Date(s).toLocaleDateString('en-CA') : '-';
const fmtDateTime = s => s ? new Date(s).toLocaleString('en-CA',{dateStyle:'short',timeStyle:'short'}) : '-';
const badge = s => `<span class="badge badge-${s||'active'}">${s||'active'}</span>`;
const cutoff = days => { const d=new Date(); d.setDate(d.getDate()-days); return d.toISOString(); };
const trunc = (s,n) => s && s.length>n ? s.substring(0,n)+'...' : (s||'-');
const escHtml = s => s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';

function filterByDate(arr, days, dateField='created_at') {
  const c = cutoff(days);
  return arr.filter(r => (r[dateField]||'') >= c);
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
const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';

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
function groupByCallType(rows) {
  const grouped = {};
  rows.forEach(r => {
    const key = r.api_call_type || 'unknown';
    if(!grouped[key]) grouped[key] = {call_type:key, requests:0, prompt:0, completion:0, total:0, cacheRead:0, cacheWrite:0, tools:0, estimated:0};
    const meta = parseMeta(r.request_metadata);
    const cache = getCacheTokens(r.request_metadata);
    grouped[key].requests += 1;
    grouped[key].prompt += r.prompt_tokens || 0;
    grouped[key].completion += r.completion_tokens || 0;
    grouped[key].total += r.total_tokens || 0;
    grouped[key].cacheRead += cache.read;
    grouped[key].cacheWrite += cache.write;
    grouped[key].tools += meta.tool_call_count || 0;
    if((meta.token_source || '').toLowerCase().includes('estimated')) grouped[key].estimated += 1;
  });
  return Object.values(grouped).sort((a,b) => (b.total || (b.prompt + b.completion)) - (a.total || (a.prompt + a.completion)));
}
function metadataSummary(meta) {
  const parts = [];
  if(meta.batch_size) parts.push(`batch=${meta.batch_size}`);
  if(meta.dimensions) parts.push(`dims=${meta.dimensions}`);
  if(meta.image_size_bytes) parts.push(`image=${fmt(meta.image_size_bytes)} bytes`);
  if(meta.cache_ttl_seconds) parts.push(`ttl=${meta.cache_ttl_seconds}s`);
  if(meta.tool_call_count) parts.push(`tools=${meta.tool_call_count}`);
  if(meta.standard_input_tokens) parts.push(`standard_in=${fmt(meta.standard_input_tokens)}`);
  if(meta.token_source) parts.push(`source=${meta.token_source}`);
  return parts.join(' · ') || JSON.stringify(meta).substring(0,140);
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
function fmtBytes(bytes) {
  bytes = Number(bytes || 0);
  if(!bytes) return '-';
  if(bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  if(bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${fmt(bytes)} B`;
}
function payloadTextChunks(meta) {
  const chunks = meta.input_text_chunks;
  if(Array.isArray(chunks)) return chunks;
  if(meta.input_text) return [meta.input_text];
  return [];
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
function togglePanel(panelId, buttonId) {
  const panel = document.getElementById(panelId);
  const button = document.getElementById(buttonId);
  const isHidden = panel.style.display === 'none' || !panel.style.display;
  panel.style.display = isHidden ? 'block' : 'none';
  if(button) {
    const label = panelId === 'charts-panel' ? 'charts' : 'details';
    button.textContent = `${isHidden ? 'Hide' : 'Show'} ${label}`;
  }
}
function renderBars(rows, valueKey, labelKey, formatter, colorClass='') {
  const maxValue = Math.max(1, ...rows.map(r => r[valueKey] || 0));
  return rows.map(r => {
    const value = r[valueKey] || 0;
    const pct = Math.max(1, Math.round((value / maxValue) * 100));
    return `<div class="bar-row">
      <div class="bar-label" title="${escHtml(r[labelKey])}">${escHtml(r[labelKey])}</div>
      <div class="bar-track"><div class="bar-fill ${colorClass}" style="width:${pct}%"></div></div>
      <div class="bar-value">${formatter(value)}</div>
    </div>`;
  }).join('');
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
  const fileTokens = files.reduce((a,r) => a+(r.filestore_token_count||0), 0);
  const totalWebsites = websites.length;
  const webTokens = websites.reduce((a,r) => a+(r.filestore_token_count||0), 0);

  // Token log cache totals
  let totalCacheReadTokens = 0, totalCacheWriteTokens = 0;
  tokenLog.forEach(r => {
    const c = getCacheTokens(r.request_metadata);
    totalCacheReadTokens += c.read;
    totalCacheWriteTokens += c.write;
  });

  // Note: totalPromptTokens in DB includes totalCacheReadTokens.
  // Subtract cached tokens to show standard input separately.
  const standardInputTokens = Math.max(0, totalPromptTokens - totalCacheReadTokens);
  const otherApiTokens = tokenLog
    .filter(r => !['agent_stream','rag'].includes(r.api_call_type||''))
    .reduce((a,r) => a + (r.total_tokens||0), 0);

  // === TOKEN SUMMARY ===
  document.getElementById('token-summary').innerHTML = `
    <h2>Token Usage Summary</h2>
    <div class="token-grid">
      <div class="token-item">
        <div class="token-label">Total Reported Tokens</div>
        <div class="token-value">${fmt(totalPromptTokens + totalCompletionTokens + otherApiTokens)}</div>
        <div class="token-detail">Chat, cache, embeddings, vision, and other logged calls</div>
      </div>
      <div class="token-item">
        <div class="token-label">Standard Input</div>
        <div class="token-value" style="font-size:20px">${fmt(standardInputTokens)}</div>
        <div class="token-detail">Prompt tokens excluding cache read tokens</div>
      </div>
      <div class="token-item">
        <div class="token-label">Output</div>
        <div class="token-value" style="font-size:20px">${fmt(totalCompletionTokens)}</div>
        <div class="token-detail">Completion tokens from chat sessions</div>
      </div>
      <div class="token-item">
        <div class="token-label">Cache Read</div>
        <div class="token-value" style="font-size:20px">${fmt(totalCacheReadTokens)}</div>
        <div class="token-detail">Cached input tokens reported by logged API calls</div>
      </div>
      <div class="token-item">
        <div class="token-label">Cache Write</div>
        <div class="token-value" style="font-size:20px">${fmt(totalCacheWriteTokens)}</div>
        <div class="token-detail">Cache creation tokens from logged API calls</div>
      </div>
      <div class="token-item">
        <div class="token-label">Other API Usage</div>
        <div class="token-value" style="font-size:20px">${fmt(otherApiTokens)}</div>
        <div class="token-detail">${fmt(otherApiTokens)} tokens from embeddings, vision, and other logged calls</div>
      </div>
    </div>
  `;

  // === KPIs ===
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="label">Total Sessions</div><div class="value accent">${fmt(totalSessions)}</div><div class="sub">${fmt(totalMsgs)} messages total</div></div>
    <div class="kpi"><div class="label">Standard Input Tokens</div><div class="value green">${fmt(standardInputTokens)}</div><div class="sub">Prompt tokens excluding cache reads</div></div>
    <div class="kpi"><div class="label">Output Tokens (Completion)</div><div class="value cyan">${fmt(totalCompletionTokens)}</div><div class="sub">Chat completion tokens</div></div>
    <div class="kpi"><div class="label">Cache Read Tokens</div><div class="value accent2">${fmt(totalCacheReadTokens)}</div><div class="sub">Reported cached input tokens</div></div>
    <div class="kpi"><div class="label">Cache Write Tokens</div><div class="value processing">${fmt(totalCacheWriteTokens)}</div><div class="sub">Reported cache creation tokens</div></div>
    <div class="kpi"><div class="label">Other API Tokens</div><div class="value red">${fmt(otherApiTokens)}</div><div class="sub">Embeddings, vision, and logged calls</div></div>
    <div class="kpi"><div class="label">Files Uploaded</div><div class="value orange">${fmt(totalFiles)}</div><div class="sub">${fmt(fileTokens)} tokens indexed</div></div>
  `;

  // === INSIGHTS ===
  document.getElementById('usage-insights').innerHTML = '';

  // === CHARTS (HIDDEN BY DEFAULT) ===
  const tokenRows = [
    {label:'Standard input', value:standardInputTokens},
    {label:'Output', value:totalCompletionTokens},
    {label:'Cache read', value:totalCacheReadTokens},
    {label:'Cache write', value:totalCacheWriteTokens},
    {label:'Other API', value:otherApiTokens},
    {label:'Indexed files', value:fileTokens},
    {label:'Indexed websites', value:webTokens}
  ].filter(r => r.value > 0);
  const callTypeTokenRows = groupedCalls
    .map(g => ({label:callTypeLabel(g.call_type), value:g.total || (g.prompt + g.completion)}))
    .filter(r => r.value > 0)
    .slice(0,10);
  document.getElementById('charts-grid').innerHTML = `
    <div class="chart-card">
      <h3>Token Breakdown</h3>
      ${renderBars(tokenRows, 'value', 'label', fmt, 'cyan') || '<p style="color:var(--muted);font-size:13px">No token data in this window</p>'}
    </div>
    <div class="chart-card">
      <h3>Tokens By Call Type</h3>
      ${renderBars(callTypeTokenRows, 'value', 'label', fmt, 'orange') || '<p style="color:var(--muted);font-size:13px">No API rows in this window</p>'}
    </div>
  `;

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
    sessionRow.innerHTML = `
      <td class="mono">${r.id}</td>
      <td>${fmtDateTime(r.started_at)}</td><td>${r.message_count||0}</td>
      <td class="token-cell">${fmt(r.total_prompt_token_count)}</td>
      <td class="token-cell">${fmt(r.total_completion_token_count)}</td>
      <td class="token-cell">${fmt((r.total_system_prompt_token_count||0)+(r.total_history_token_count||0)+(r.total_tool_def_token_count||0))}</td>
      <td class="token-cell">${fmt((r.total_user_msg_token_count||0)+(r.total_bot_response_token_count||0))}</td>
      <td>${badge(r.archive_status)}</td>`;
    sessionRow.onclick = function() { toggleSession(this, r.id); };
    sessionsEl.appendChild(sessionRow);
  });

  // === TOKEN USAGE LOG TABLE ===
  document.getElementById('token-log-table').innerHTML = tokenLog.slice(0,300).map(r => {
    const meta = parseMeta(r.request_metadata);
    const cache = getCacheTokens(r.request_metadata);
    const chunks = payloadTextChunks(meta);
    return `<tr class="session-row" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'table-row':'none';this.classList.toggle('open')">
      <td>${fmtDateTime(r.created_at)}</td>
      <td>${callTypeLabel(r.api_call_type)}</td>
      <td>${r.model||'-'}</td>
      <td class="token-cell">${fmt(r.total_tokens || ((r.prompt_tokens||0)+(r.completion_tokens||0)))}</td>
      <td class="token-cell">${fmt(r.prompt_tokens)}</td>
      <td class="token-cell">${fmt(r.completion_tokens)}</td>
      <td class="token-cell">${fmt(cache.read + cache.write)}</td>
      <td>${payloadChars(meta) ? fmt(payloadChars(meta)) : '-'}</td>
      <td>${payloadWords(meta) ? fmt(payloadWords(meta)) : '-'}</td>
      <td>${fmtBytes(payloadBytes(meta))}</td>
      <td style="max-width:200px" class="mono"><div class="bd-text-preview" title="${meta.source_url||''}" onclick="event.stopPropagation();if(this.title)window.open(this.title,'_blank')">${meta.source_url ? meta.source_url.split('/').pop() || meta.source_url : '-'}</div></td>
      <td><div class="metadata-snippet" title="${escHtml(JSON.stringify(meta))}">${escHtml(metadataSummary(meta))}</div></td>
    </tr>
    <tr class="msg-row" style="display:none">
      <td colspan="12">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
          <div>
            <div style="font-size:12px;color:var(--muted);margin-bottom:4px">${chunks.length ? `${fmt(chunks.length)} captured text chunk${chunks.length===1?'':'s'}` : 'Text payload details'}</div>
            ${meta.source_url ? `<div style="font-size:11px;color:var(--accent);font-weight:600">Source: <a href="${meta.source_url}" target="_blank" style="color:inherit;text-decoration:none">${meta.source_url}</a></div>` : ''}
          </div>
          <div style="font-size:10px;color:var(--muted);background:rgba(0,0,0,.04);padding:4px 8px;border-radius:4px">
            Model: ${r.model} | Provider: ${r.provider}
          </div>
        </div>
        ${renderPayloadText(meta)}
      </td>
    </tr>`;
  }).join('');
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
      Agent Run Steps (${steps.length} steps, ${fmt(totalTokens)} total tokens) [show/hide]
    </div>
    <div style="display:none">
    <table class="bd-table" style="margin:0">
      <thead><tr><th>#</th><th>Direction</th><th>Part Type</th><th>Tool</th><th style="text-align:right">Tokens</th><th style="text-align:right">Words</th><th style="text-align:right">Chars</th><th>Content (click to expand)</th></tr></thead>
      <tbody>`;
  steps.forEach(s => {
    html += `<tr>
      <td style="font-weight:600">${s.step_number}</td>
      <td><span style="font-size:10px;padding:2px 6px;border-radius:4px;background:${s.step_type==='model_request'?'rgba(37,99,235,.1)':'rgba(22,163,74,.1)'};color:${s.step_type==='model_request'?'var(--blue)':'var(--green)'}">${s.step_type==='model_request'?'INPUT':'OUTPUT'}</span></td>
      <td style="color:${partColor(s.part_type)};font-weight:600">${partLabel(s.part_type)}</td>
      <td style="font-size:11px">${s.tool_name||'-'}</td>
      <td class="bd-num">${fmt(s.token_count)}</td>
      <td class="bd-num">${fmt(s.word_count)}</td>
      <td class="bd-num">${fmt(s.char_count)}</td>
      <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(s.content_preview)}</div></td>
    </tr>`;
  });
  html += `</tbody></table></div></div>`;
  return html;
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

  const chatMsgs = RAW.chat_messages || [];
  const msgs = chatMsgs.filter(m => m.session_id === sessionId)
    .sort((a,b) => (a.created_at||'').localeCompare(b.created_at||''));

  if(msgs.length === 0) {
    const emptyRow = document.createElement('tr');
    emptyRow.className = 'msg-row';
    emptyRow.innerHTML = `<td colspan="8" style="color:var(--muted);font-style:italic;padding-left:32px">No messages found for this session</td>`;
    rowEl.after(emptyRow);
    return;
  }

  const roleName = r => r==='assistant'?'Bot':r==='user'?'User':r==='human_agent'?'Human Agent':(r||'Unknown');

  let insertAfter = rowEl;
  msgs.forEach((m, idx) => {
    const msgRow = document.createElement('tr');
    msgRow.className = 'msg-row';

    msgRow.innerHTML = `<td colspan="8" style="padding-left:24px">
      <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:8px">
        <span class="badge badge-${m.role}" style="flex-shrink:0">${roleName(m.role)}</span>
        <div class="msg-bubble msg-collapsed" onclick="this.classList.toggle('msg-collapsed')" title="Click to expand/collapse" style="flex:1">${escHtml(m.content)}</div>
        <span style="flex-shrink:0;font-size:11px;color:var(--muted);white-space:nowrap">${fmtDateTime(m.created_at)}</span>
      </div>
      <table class="bd-table">
        <thead><tr>
          <th>Component</th><th style="text-align:right">Tokens</th><th style="text-align:right">Words</th><th style="text-align:right">Chars</th><th>Content (click to expand)</th>
        </tr></thead>
        <tbody>
        ${m.role==='user' ? `
          <tr>
            <td class="bd-label">System Prompt</td>
            <td class="bd-num">${fmt(m.system_prompt_token_count)}</td>
            <td class="bd-num">${fmt(m.system_prompt_word_count)}</td>
            <td class="bd-num">${fmt(m.system_prompt_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.system_prompt_text)||'-'}</div></td>
          </tr>
          <tr>
            <td class="bd-label">Conv. History</td>
            <td class="bd-num">${fmt(m.history_token_count)}</td>
            <td class="bd-num">${fmt(m.history_word_count)}</td>
            <td class="bd-num">${fmt(m.history_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.history_text)||'<i style="color:var(--muted)">No history (first message)</i>'}</div></td>
          </tr>
          <tr>
            <td class="bd-label">Tools + Multi-turn</td>
            <td class="bd-num">${fmt(m.tool_def_token_count)}</td>
            <td class="bd-num" colspan="2" style="text-align:left;font-weight:400;font-size:10px;color:var(--muted)">Derived: Total Prompt - others</td>
            <td class="bd-text" style="font-size:10px;color:var(--muted)">Includes tool schema, tool call/return context, repeated prompt across turns</td>
          </tr>
          <tr>
            <td class="bd-label">User Message</td>
            <td class="bd-num">${fmt(m.user_msg_token_count)}</td>
            <td class="bd-num">${fmt(m.user_msg_word_count)}</td>
            <td class="bd-num">${fmt(m.user_msg_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.content)||'-'}</div></td>
          </tr>
          <tr style="background:rgba(79,70,229,.06);font-weight:600">
            <td class="bd-label">Total (Prompt)</td>
            <td class="bd-num">${fmt(m.prompt_token_count)}</td>
            <td colspan="2" style="font-size:11px;color:var(--muted)">Billable input from Gemini API</td>
            <td></td>
          </tr>
        ` : `
          <tr>
            <td class="bd-label">Bot Response</td>
            <td class="bd-num">${fmt(m.bot_response_token_count)}</td>
            <td class="bd-num">${fmt(m.bot_response_word_count)}</td>
            <td class="bd-num">${fmt(m.bot_response_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.content)||'-'}</div></td>
          </tr>
          <tr style="background:rgba(79,70,229,.06);font-weight:600">
            <td class="bd-label">Total (Completion)</td>
            <td class="bd-num">${fmt(m.completion_token_count)}</td>
            <td colspan="2" style="font-size:11px;color:var(--muted)">Output tokens include tool call generation + final response</td>
            <td></td>
          </tr>
        `}
        </tbody>
      </table>
      ${m.role==='user' ? renderRunSteps(m.id, sessionId) : ''}
      <div style="font-size:10px;color:var(--muted);margin-top:2px">ID: ${m.id||'-'}</div>
    </td>`;
    insertAfter.after(msgRow);
    insertAfter = msgRow;
  });
}

// === EXCEL DOWNLOAD (multi-sheet XLSX via SheetJS) ===
function downloadExcel() {
  const days = currentDays;
  const sessions = filterByDate(RAW.sessions, days);
  const chatMsgs = filterByDate(RAW.chat_messages||[], days);
  const tokenLog = filterByDate(RAW.token_usage_log||[], days);

  const wb = XLSX.utils.book_new();

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
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sessData), 'Chat Sessions');

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
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(msgData), 'Chat Messages');

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
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(stepsData), 'Agent Run Steps');

  // Sheet 4: API Token Usage Log
  const tokenLogData = tokenLog.map(r => {
    const meta = parseMeta(r.request_metadata);
    const cache = getCacheTokens(r.request_metadata);
    return {
      'Created': r.created_at||'',
      'Session ID': r.session_id||'',
      'Message ID': r.message_id||'',
      'Provider': r.provider||'',
      'Model': r.model||'',
      'Call Type': callTypeLabel(r.api_call_type),
      'Prompt Tokens': r.prompt_tokens||0,
      'Completion Tokens': r.completion_tokens||0,
      'Total Tokens': r.total_tokens||0,
      'Cache Tokens': cache.read + cache.write,
      'Standard Input Tokens': meta.standard_input_tokens||Math.max(0, (r.prompt_tokens||0) - cache.read),
      'Input Characters': payloadChars(meta),
      'Input Words': payloadWords(meta),
      'Input Size Bytes': payloadBytes(meta),
      'Input Size': fmtBytes(payloadBytes(meta)),
      'Input Text Chunks': payloadTextChunks(meta).join('\\n\\n--- chunk ---\\n\\n'),
      'Input Text Truncated': meta.input_text_truncated ? 'yes' : 'no',
      'Tool Calls': meta.tool_call_count||0,
      'Token Source': meta.token_source||'',
      'Context': metadataSummary(meta)
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tokenLogData), 'API Token Usage');

  // Sheet 5: Usage By Call Type
  const groupedUsageData = groupByCallType(tokenLog).map(g => ({
    'Call Type': callTypeLabel(g.call_type),
    'Raw Call Type': g.call_type,
    'Requests': g.requests,
    'Prompt Tokens': g.prompt,
    'Completion Tokens': g.completion,
    'Total Tokens': g.total || (g.prompt + g.completion),
    'Cache Read Tokens': g.cacheRead,
    'Cache Write Tokens': g.cacheWrite,
    'Tool Calls': g.tools,
    'Rows With Estimated Tokens': g.estimated
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(groupedUsageData), 'Usage By Call Type');

  // Sheet 6: Largest Token Calls
  const topCallsData = [...tokenLog].sort((a,b) => (b.total_tokens||0) - (a.total_tokens||0)).slice(0,100).map(r => {
    const meta = parseMeta(r.request_metadata);
    return {
      'Created': r.created_at||'',
      'Call Type': callTypeLabel(r.api_call_type),
      'Provider': r.provider||'',
      'Model': r.model||'',
      'Prompt Tokens': r.prompt_tokens||0,
      'Completion Tokens': r.completion_tokens||0,
      'Total Tokens': r.total_tokens||0,
      'Token Source': meta.token_source||'',
      'Context': metadataSummary(meta),
      'Session ID': r.session_id||'',
      'Message ID': r.message_id||''
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(topCallsData), 'Largest Token Calls');

  XLSX.writeFile(wb, `usage-report-${days}d-${new Date().toISOString().substring(0,10)}.xlsx`);
}


// === INIT ===
render();
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
