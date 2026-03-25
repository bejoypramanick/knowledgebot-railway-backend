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

        messages = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT DATE(created_at) as day, role,
                   COUNT(*) as msg_count,
                   COALESCE(SUM(token_count), 0) as total_tokens,
                   COALESCE(SUM(character_count), 0) as total_chars,
                   COALESCE(SUM(word_count), 0) as total_words,
                   COALESCE(AVG(character_count), 0) as avg_chars,
                   COALESCE(AVG(word_count), 0) as avg_words,
                   COALESCE(AVG(token_count), 0) as avg_tokens
            FROM chat_messages WHERE created_at >= :since
            GROUP BY DATE(created_at), role ORDER BY day
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

        token_usage_log = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT id, session_id, message_id, provider, model,
                   prompt_tokens, completion_tokens, total_tokens,
                   cost_cents, api_call_type, request_metadata, created_at
            FROM token_usage_log
            WHERE created_at >= :since
            ORDER BY created_at DESC
        """), {"since": since})).fetchall()]

        tables_metadata = [_row_to_dict(r) for r in (await db.execute(text("""
            SELECT tm.id, tm.file_upload_id, tm.scraped_website_id,
                   tm.table_index, tm.table_column_count_input, tm.table_row_count_input,
                   tm.table_character_count_input, tm.table_word_count_input,
                   tm.table_word_count_output, tm.table_character_count_output,
                   tm.table_input_token_count, tm.table_output_token_count,
                   tm.created_at,
                   COALESCE(fu.original_filename, sw.original_url) as source_name,
                   CASE WHEN tm.file_upload_id IS NOT NULL THEN 'file' ELSE 'web' END as source_type
            FROM tables_metadata tm
            LEFT JOIN file_uploads fu ON tm.file_upload_id = fu.id
            LEFT JOIN scraped_websites sw ON tm.scraped_website_id = sw.id
            WHERE tm.created_at >= :since
            ORDER BY tm.created_at DESC
        """), {"since": since})).fetchall()]

    return {
        "sessions": sessions, "messages": messages, "files": files,
        "websites": websites, "chat_messages": chat_messages,
        "run_steps": run_steps, "token_usage_log": token_usage_log,
        "tables_metadata": tables_metadata
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
.cost-cell{font-weight:600;color:var(--green)}
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
.cost-summary{background:linear-gradient(135deg,#f0fdf4,#ecfdf5);border:1px solid #86efac;border-radius:12px;padding:20px;margin-bottom:32px}
.cost-summary h2{font-size:20px;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #86efac;color:#166534}
.cost-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}
.cost-item{background:#fff;border:1px solid #bbf7d0;border-radius:8px;padding:16px}
.cost-item .cost-label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.cost-item .cost-value{font-size:24px;font-weight:700;color:#166534}
.cost-item .cost-detail{font-size:11px;color:var(--muted);margin-top:4px}
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
<h3>Metric Definitions & Pricing <span style="font-size:12px;color:var(--muted);font-weight:400;cursor:pointer" onclick="document.getElementById('legend-detail').style.display=document.getElementById('legend-detail').style.display==='none'?'block':'none'">[show/hide]</span></h3>
<div id="legend-detail" class="legend-grid" style="display:none">
  <div class="legend-section">
    <h4>Chat Message Metrics (per message)</h4>
    <dl>
      <dt>Characters</dt><dd>Total characters in the message text, including spaces, punctuation, and emojis</dd>
      <dt>Words</dt><dd>Total words in the message text (split by whitespace)</dd>
      <dt>Msg Tokens</dt><dd>Gemini tokens for ONLY the message text itself (via count_tokens API). A "hi" = ~1 token</dd>
      <dt>Prompt Tokens</dt><dd>Total tokens sent TO Gemini for this turn: system prompt + conversation history + tool definitions + the user message. This is the billable input</dd>
      <dt>Completion Tokens</dt><dd>Total tokens generated BY Gemini as the response. Only set on bot messages. This is the billable output</dd>
    </dl>
  </div>
  <div class="legend-section">
    <h4>Prompt Component Breakdown (per user message)</h4>
    <dl>
      <dt>System Prompt</dt><dd>The persona instructions + RAG enforcement rules sent at the start of every turn. Chars/words/tokens counted separately via count_tokens API</dd>
      <dt>History</dt><dd>All prior user + bot messages in the conversation, serialized as text. Grows with each turn. Chars/words/tokens counted separately</dd>
      <dt>Tools + Multi-turn</dt><dd>Derived as: Total Prompt - System Prompt - History - User Msg. Includes the full Gemini tool schema, tool call/return context in multi-turn runs, and repeated prompt overhead when tools are invoked</dd>
      <dt>User Msg</dt><dd>Just the current user message text. Chars/words/tokens counted separately. Same as Msg Tokens but stored in dedicated columns</dd>
      <dt>Bot Response</dt><dd>Just the bot's generated response text. Chars/words/tokens stored on the assistant message row</dd>
    </dl>
  </div>
  <div class="legend-section">
    <h4>Gemini 2.5 Flash Lite Pricing (Paid Tier, per 1M tokens)</h4>
    <dl>
      <dt>Input (text/image/video)</dt><dd>$0.10 / 1M tokens</dd>
      <dt>Output</dt><dd>$0.40 / 1M tokens</dd>
      <dt>Cached Input (text/image/video)</dt><dd>$0.01 / 1M tokens (90% discount)</dd>
      <dt>Cache Storage</dt><dd>$1.00 / hour / 1M tokens</dd>
      <dt>Table Formatting (Flash)</dt><dd>Input: $0.10 / 1M, Output: $0.40 / 1M (same model)</dd>
    </dl>
  </div>
  <!-- Token Usage Log legend removed as requested -->
  <div class="legend-section">
    <h4>Table Formatting Metrics (Gemini Flash)</h4>
    <dl>
      <dt>Tables Count</dt><dd>Number of tables detected in the document by docling</dd>
      <dt>Table Input Tokens</dt><dd>Tokens sent to Gemini Flash for table formatting (raw docling table data + metadata)</dd>
      <dt>Table Output Tokens</dt><dd>Tokens generated by Gemini Flash as formatted table JSON</dd>
      <dt>Cost</dt><dd>Computed using same model pricing as chat (Gemini 2.5 Flash Lite rates)</dd>
    </dl>
  </div>
  <div class="legend-section">
    <h4>Chat Session Metrics (aggregate across all messages)</h4>
    <dl>
      <dt>Chars</dt><dd>Sum of character counts from all user + bot messages in the session</dd>
      <dt>Words</dt><dd>Sum of word counts from all user + bot messages in the session</dd>
      <dt>Msg Tokens</dt><dd>Sum of message-only token counts from all messages in the session</dd>
      <dt>Prompt Tokens</dt><dd>Sum of all prompt tokens across all turns (total billable input for the session)</dd>
      <dt>Completion Tokens</dt><dd>Sum of all completion tokens across all turns (total billable output for the session)</dd>
    </dl>
  </div>
  <div class="legend-section">
    <h4>File Upload & Website Metrics</h4>
    <dl>
      <dt>File Size</dt><dd>Size of the original uploaded file in bytes</dd>
      <dt>Markdown Chars/Words/Tokens</dt><dd>Processed content sent to Gemini FileSearch (after docling + Gemini table formatting)</dd>
      <dt>Table Input/Output Tokens</dt><dd>Gemini tokens consumed for formatting tables within the document</dd>
    </dl>
  </div>
</div>
</div>

<!-- Cost Summary -->
<div class="cost-summary" id="cost-summary"></div>

<div class="kpi-grid" id="kpis"></div>

<div class="section"><h2>Chat Sessions <span style="font-size:13px;color:var(--muted);font-weight:400">(click to expand messages)</span></h2><div class="table-wrap" style="max-height:700px"><table>
  <thead><tr><th>Session ID</th><th>Started</th><th title="Total messages (user + bot + human agent) in this session">Msgs</th><th title="Sum of all characters from every message in this session">Chars</th><th title="Sum of all words from every message in this session">Words</th><th title="Sum of Gemini tokens for ONLY the message text of each message (count_tokens API)">Msg Tokens</th><th title="Sum of total tokens sent TO Gemini across all turns (billable input)">Prompt Tokens</th><th title="Sum of tokens generated BY Gemini across all turns (billable output)">Completion Tokens</th><th title="Sum of system prompt tokens across all turns">Sys Prompt Tok</th><th title="Sum of conversation history tokens across all turns">History Tok</th><th title="Sum of tool definition tokens across all turns">Tool Def Tok</th><th title="Sum of user message text tokens across all turns">User Msg Tok</th><th title="Sum of bot response text tokens across all turns">Bot Resp Tok</th><th title="Estimated cost using Gemini 2.5 Flash Lite pricing">Est. Cost</th><th>Duration</th><th>Status</th></tr></thead>
  <tbody id="sessions-table"></tbody>
</table></div></div>

<div class="section"><h2>File Uploads</h2><div class="table-wrap"><table>
  <thead><tr><th>Filename</th><th>Ext</th><th title="Size of the original uploaded file in bytes">File Size</th><th title="Characters in the processed Markdown sent to Gemini FileSearch">Markdown Chars</th><th title="Words in the processed Markdown sent to Gemini FileSearch">Markdown Words</th><th title="Gemini tokens for the processed Markdown (count_tokens API)">Markdown Tokens</th><th title="Number of tables formatted by Gemini">Tables</th><th title="Tokens sent to Gemini for table formatting">Table Input Tok</th><th title="Tokens generated by Gemini for table formatting">Table Output Tok</th><th title="Estimated cost for table formatting">Table Format Cost</th><th>Status</th><th>Date</th></tr></thead>
  <tbody id="files-table"></tbody>
</table></div></div>

<div class="section"><h2>Scraped Websites</h2><div class="table-wrap"><table>
  <thead><tr><th>URL</th><th>Title</th><th title="Number of web pages successfully crawled">Pages</th><th title="Characters in the processed Markdown sent to Gemini FileSearch">Markdown Chars</th><th title="Words in the processed Markdown sent to Gemini FileSearch">Markdown Words</th><th title="Gemini tokens for the processed Markdown (count_tokens API)">Markdown Tokens</th><th title="Number of tables formatted by Gemini">Tables</th><th title="Tokens sent to Gemini for table formatting">Table Input Tok</th><th title="Tokens generated by Gemini for table formatting">Table Output Tok</th><th title="Estimated cost for table formatting">Table Format Cost</th><th>Status</th><th>Date</th></tr></thead>
  <tbody id="websites-table"></tbody>
</table></div></div>

<div class="section"><h2>Table Formatting Detail <span style="font-size:13px;color:var(--muted);font-weight:400">(Gemini Flash per-table costs)</span></h2><div class="table-wrap"><table>
  <thead><tr><th>Source</th><th>Type</th><th>Table #</th><th>Cols</th><th>Rows</th><th>Input Chars</th><th>Output Chars</th><th>Input Tokens</th><th>Output Tokens</th><th>Est. Cost</th><th>Date</th></tr></thead>
  <tbody id="tables-meta-table"></tbody>
</table></div></div>

<!-- Token Usage Log section removed as requested -->

</div>

<script>
// === DATA ===
const RAW = """ + data_json + """;
let currentDays = 30;

// === GEMINI 2.5 FLASH LITE PRICING (Paid Tier, per 1M tokens, USD) ===
const PRICING = {
  input_per_1m: 0.10,        // $0.10 per 1M input tokens (text/image/video)
  output_per_1m: 0.40,       // $0.40 per 1M output tokens
  cache_read_per_1m: 0.01,   // $0.01 per 1M cached input tokens (90% discount)
  cache_write_per_1m: 0.10,  // Same as input rate (cache write = standard input cost)
  cache_storage_per_hr: 1.00 // $1.00 per hour per 1M tokens stored
};

// Cost calculation helpers
function calcInputCost(tokens) { return (tokens / 1_000_000) * PRICING.input_per_1m; }
function calcOutputCost(tokens) { return (tokens / 1_000_000) * PRICING.output_per_1m; }
function calcCacheReadCost(tokens) { return (tokens / 1_000_000) * PRICING.cache_read_per_1m; }
function calcCacheWriteCost(tokens) { return (tokens / 1_000_000) * PRICING.cache_write_per_1m; }
function calcSessionCost(promptTokens, completionTokens) {
  return calcInputCost(promptTokens) + calcOutputCost(completionTokens);
}
function calcTableCost(inputTokens, outputTokens) {
  return calcInputCost(inputTokens) + calcOutputCost(outputTokens);
}
function fmtCost(usd) {
  if(usd >= 0.01) return '$' + usd.toFixed(4);
  if(usd > 0) return '$' + usd.toFixed(6);
  return '$0.00';
}

// === HELPERS ===
const fmt = n => (n||0).toLocaleString();
const fmtDate = s => s ? new Date(s).toLocaleDateString('en-CA') : '-';
const fmtDateTime = s => s ? new Date(s).toLocaleString('en-CA',{dateStyle:'short',timeStyle:'short'}) : '-';
const badge = s => `<span class="badge badge-${s||'active'}">${s||'active'}</span>`;
const cutoff = days => { const d=new Date(); d.setDate(d.getDate()-days); return d.toISOString(); };
const trunc = (s,n) => s && s.length>n ? s.substring(0,n)+'...' : (s||'-');

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
  const messages = filterByDate(RAW.messages, days, 'day');
  const files = filterByDate(RAW.files, days);
  const websites = filterByDate(RAW.websites, days);
  const tokenLog = filterByDate(RAW.token_usage_log||[], days);
  const tablesMeta = filterByDate(RAW.tables_metadata||[], days);

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

  // Table formatting totals
  const totalTableInputTokens = tablesMeta.reduce((a,r) => a+(r.table_input_token_count||0), 0);
  const totalTableOutputTokens = tablesMeta.reduce((a,r) => a+(r.table_output_token_count||0), 0);

  // Token log cache totals
  let totalCacheReadTokens = 0, totalCacheWriteTokens = 0;
  tokenLog.forEach(r => {
    const c = getCacheTokens(r.request_metadata);
    totalCacheReadTokens += c.read;
    totalCacheWriteTokens += c.write;
  });

  // === COST CALCULATIONS ===
  // Note: totalPromptTokens in DB includes totalCacheReadTokens.
  // We must subtract cached tokens to get the standard (non-cached) input tokens.
  const standardInputTokens = Math.max(0, totalPromptTokens - totalCacheReadTokens);
  
  const chatInputCost = calcInputCost(standardInputTokens);
  const chatOutputCost = calcOutputCost(totalCompletionTokens);
  const chatCost = chatInputCost + chatOutputCost;
  const cacheReadCost = calcCacheReadCost(totalCacheReadTokens);
  const cacheWriteCost = calcCacheWriteCost(totalCacheWriteTokens);
  const tableFormatCost = calcTableCost(totalTableInputTokens, totalTableOutputTokens);
  const totalEstCost = chatCost + cacheReadCost + cacheWriteCost + tableFormatCost;

  // === COST SUMMARY ===
  document.getElementById('cost-summary').innerHTML = `
    <h2>Estimated Cost Summary (Gemini 2.5 Flash Lite Paid Tier)</h2>
    <div class="cost-grid">
      <div class="cost-item">
        <div class="cost-label">Total Estimated Cost</div>
        <div class="cost-value">${fmtCost(totalEstCost)}</div>
        <div class="cost-detail">All Gemini API usage combined</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Chat Input (Standard)</div>
        <div class="cost-value" style="font-size:20px">${fmtCost(chatInputCost)}</div>
        <div class="cost-detail">${fmt(standardInputTokens)} non-cached tokens @ $0.10/1M</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Chat Output (Completion)</div>
        <div class="cost-value" style="font-size:20px">${fmtCost(chatOutputCost)}</div>
        <div class="cost-detail">${fmt(totalCompletionTokens)} tokens @ $0.40/1M</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Cache Read (90% discount)</div>
        <div class="cost-value" style="font-size:20px">${fmtCost(cacheReadCost)}</div>
        <div class="cost-detail">${fmt(totalCacheReadTokens)} tokens @ $0.01/1M</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Cache Write</div>
        <div class="cost-value" style="font-size:20px">${fmtCost(cacheWriteCost)}</div>
        <div class="cost-detail">${fmt(totalCacheWriteTokens)} tokens @ $0.10/1M</div>
      </div>
      <div class="cost-item">
        <div class="cost-label">Table Formatting</div>
        <div class="cost-value" style="font-size:20px">${fmtCost(tableFormatCost)}</div>
        <div class="cost-detail">${fmt(totalTableInputTokens)} in + ${fmt(totalTableOutputTokens)} out tokens</div>
      </div>
    </div>
    <div style="margin-top:12px;font-size:11px;color:#6b7280">
      Pricing: Input $0.10/1M | Output $0.40/1M | Cached Input $0.01/1M | Cache Storage $1.00/hr/1M tokens (not tracked here).
      FileSearch upload/storage costs are billed separately by Google and not tracked in this report.
    </div>
  `;

  // === KPIs ===
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="label">Total Sessions</div><div class="value accent">${fmt(totalSessions)}</div><div class="sub">${fmt(totalMsgs)} messages total</div></div>
    <div class="kpi"><div class="label">Standard Input Tokens</div><div class="value green">${fmt(standardInputTokens)}</div><div class="sub">${fmtCost(chatInputCost)} @ $0.10/1M</div></div>
    <div class="kpi"><div class="label">Output Tokens (Completion)</div><div class="value cyan">${fmt(totalCompletionTokens)}</div><div class="sub">${fmtCost(chatOutputCost)} @ $0.40/1M</div></div>
    <div class="kpi"><div class="label">Cache Read Tokens</div><div class="value accent2">${fmt(totalCacheReadTokens)}</div><div class="sub">${fmtCost(cacheReadCost)} @ $0.01/1M (90% off)</div></div>
    <div class="kpi"><div class="label">Cache Write Tokens</div><div class="value processing">${fmt(totalCacheWriteTokens)}</div><div class="sub">${fmtCost(cacheWriteCost)} @ $0.10/1M</div></div>
    <div class="kpi"><div class="label">Table Formatting</div><div class="value orange">${fmt(totalTableInputTokens + totalTableOutputTokens)}</div><div class="sub">${fmtCost(tableFormatCost)} (${tablesMeta.length} tables)</div></div>
    <div class="kpi"><div class="label">Files Uploaded</div><div class="value orange">${fmt(totalFiles)}</div><div class="sub">${fmt(fileTokens)} tokens indexed</div></div>
  `;

  // === HELPERS FOR MESSAGES ===
  const chatMsgs = filterByDate(RAW.chat_messages||[], days);
  const roleName = r => r==='assistant'?'Bot':r==='user'?'User':r==='human_agent'?'Human Agent':(r||'Unknown');
  const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';

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
    const cost = calcSessionCost(r.total_prompt_token_count||0, r.total_completion_token_count||0);
    const sessionRow = document.createElement('tr');
    sessionRow.className = 'session-row';
    sessionRow.dataset.sessionId = r.id;
    sessionRow.innerHTML = `
      <td class="mono">${r.id}</td>
      <td>${fmtDateTime(r.started_at)}</td><td>${r.message_count||0}</td>
      <td>${fmt(r.total_character_count)}</td><td>${fmt(r.total_word_count)}</td>
      <td class="token-cell">${fmt(r.total_message_token_count)}</td>
      <td class="token-cell">${fmt(r.total_prompt_token_count)}</td>
      <td class="token-cell">${fmt(r.total_completion_token_count)}</td>
      <td class="token-cell">${fmt(r.total_system_prompt_token_count)}</td>
      <td class="token-cell">${fmt(r.total_history_token_count)}</td>
      <td class="token-cell">${fmt(r.total_tool_def_token_count)}</td>
      <td class="token-cell">${fmt(r.total_user_msg_token_count)}</td>
      <td class="token-cell">${fmt(r.total_bot_response_token_count)}</td>
      <td class="cost-cell">${fmtCost(cost)}</td>
      <td>${r.duration_minutes||'-'}</td>
      <td>${badge(r.archive_status)}</td>`;
    sessionRow.onclick = function() { toggleSession(this, r.id); };
    sessionsEl.appendChild(sessionRow);
  });

  // === FILES TABLE ===
  document.getElementById('files-table').innerHTML = files.slice(0,100).map(r => {
    return `<tr>
    <td title="${r.original_filename}">${trunc(r.original_filename,35)}</td><td>${r.file_extension||'-'}</td>
    <td>${fmt(r.file_size)}</td><td>${fmt(r.filestore_character_count)}</td><td>${fmt(r.filestore_word_count)}</td>
    <td class="token-cell">${fmt(r.filestore_token_count)}</td>
    <td>${badge(r.processing_status)}</td>
    <td>${fmtDate(r.created_at)}</td></tr>`;
  }).join('');

  // === WEBSITES TABLE ===
  document.getElementById('websites-table').innerHTML = websites.slice(0,100).map(r => {
    return `<tr>
    <td title="${r.original_url}">${trunc(r.original_url,40)}${r.parent_id?' (child)':''}</td>
    <td>${trunc(r.title,30)}</td><td>${r.pages_scraped||0}</td>
    <td>${fmt(r.filestore_character_count)}</td><td>${fmt(r.filestore_word_count)}</td>
    <td class="token-cell">${fmt(r.filestore_token_count)}</td>
    <td>${badge(r.processing_status)}</td>
    <td>${fmtDate(r.created_at)}</td></tr>`;
  }).join('');

  // === TABLES METADATA TABLE ===
  document.getElementById('tables-meta-table').innerHTML = tablesMeta.slice(0,200).map(r => {
    <td title="${r.source_name}">
      <div style="font-weight:500;white-space:normal;word-break:break-all;max-width:300px">${r.source_name || '-'}</div>
      <div style="font-size:10px;color:var(--muted);margin-top:2px">ID: ${r.file_upload_id || r.scraped_website_id || '-'}</div>
    </td>
    <td><span class="badge badge-${r.source_type==='file'?'processing':'active'}">${r.source_type}</span></td>
    <td>${r.table_index}</td>
    <td>${r.table_column_count_input||0}</td><td>${r.table_row_count_input||0}</td>
    <td>${fmt(r.table_character_count_input)}</td><td>${fmt(r.table_character_count_output)}</td>
    <td class="token-cell">${fmt(r.table_input_token_count)}</td>
    <td class="token-cell">${fmt(r.table_output_token_count)}</td>
    <td class="cost-cell">${fmtCost(cost)}</td>
    <td>${fmtDate(r.created_at)}</td></tr>`;
  }).join('');
}

// === RENDER AGENT RUN STEPS FOR A USER MESSAGE ===
function renderRunSteps(userMsgId, sessionId) {
  const steps = (RAW.run_steps||[]).filter(s => s.user_message_id === userMsgId);
  if(steps.length === 0) return '';
  const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';
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
    emptyRow.innerHTML = `<td colspan="16" style="color:var(--muted);font-style:italic;padding-left:32px">No messages found for this session</td>`;
    rowEl.after(emptyRow);
    return;
  }

  const roleName = r => r==='assistant'?'Bot':r==='user'?'User':r==='human_agent'?'Human Agent':(r||'Unknown');
  const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';

  let insertAfter = rowEl;
  msgs.forEach((m, idx) => {
    const msgRow = document.createElement('tr');
    msgRow.className = 'msg-row';

    // Per-message cost
    let msgCost = 0;
    if(m.role==='user') msgCost = calcInputCost(m.prompt_token_count||0);
    else if(m.role==='assistant') msgCost = calcOutputCost(m.completion_token_count||0);

    msgRow.innerHTML = `<td colspan="16" style="padding-left:24px">
      <div style="display:flex;align-items:flex-start;gap:12px;margin-bottom:8px">
        <span class="badge badge-${m.role}" style="flex-shrink:0">${roleName(m.role)}</span>
        <div class="msg-bubble msg-collapsed" onclick="this.classList.toggle('msg-collapsed')" title="Click to expand/collapse" style="flex:1">${escHtml(m.content)}</div>
        <span class="cost-cell" style="flex-shrink:0;font-size:12px;white-space:nowrap">${fmtCost(msgCost)}</span>
        <span style="flex-shrink:0;font-size:11px;color:var(--muted);white-space:nowrap">${fmtDateTime(m.created_at)}</span>
      </div>
      <table class="bd-table">
        <thead><tr>
          <th>Component</th><th style="text-align:right">Tokens</th><th style="text-align:right">Words</th><th style="text-align:right">Chars</th><th style="text-align:right">Est. Cost</th><th>Content (click to expand)</th>
        </tr></thead>
        <tbody>
        ${m.role==='user' ? `
          <tr>
            <td class="bd-label">System Prompt</td>
            <td class="bd-num">${fmt(m.system_prompt_token_count)}</td>
            <td class="bd-num">${fmt(m.system_prompt_word_count)}</td>
            <td class="bd-num">${fmt(m.system_prompt_char_count)}</td>
            <td class="bd-num cost-cell">${fmtCost(calcInputCost(m.system_prompt_token_count||0))}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.system_prompt_text)||'-'}</div></td>
          </tr>
          <tr>
            <td class="bd-label">Conv. History</td>
            <td class="bd-num">${fmt(m.history_token_count)}</td>
            <td class="bd-num">${fmt(m.history_word_count)}</td>
            <td class="bd-num">${fmt(m.history_char_count)}</td>
            <td class="bd-num cost-cell">${fmtCost(calcInputCost(m.history_token_count||0))}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.history_text)||'<i style="color:var(--muted)">No history (first message)</i>'}</div></td>
          </tr>
          <tr>
            <td class="bd-label">Tools + Multi-turn</td>
            <td class="bd-num">${fmt(m.tool_def_token_count)}</td>
            <td class="bd-num" colspan="2" style="text-align:left;font-weight:400;font-size:10px;color:var(--muted)">Derived: Total Prompt - others</td>
            <td class="bd-num cost-cell">${fmtCost(calcInputCost(m.tool_def_token_count||0))}</td>
            <td class="bd-text" style="font-size:10px;color:var(--muted)">Includes tool schema, tool call/return context, repeated prompt across turns</td>
          </tr>
          <tr>
            <td class="bd-label">User Message</td>
            <td class="bd-num">${fmt(m.user_msg_token_count)}</td>
            <td class="bd-num">${fmt(m.user_msg_word_count)}</td>
            <td class="bd-num">${fmt(m.user_msg_char_count)}</td>
            <td class="bd-num cost-cell">${fmtCost(calcInputCost(m.user_msg_token_count||0))}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.content)||'-'}</div></td>
          </tr>
          <tr style="background:rgba(79,70,229,.06);font-weight:600">
            <td class="bd-label">Total (Prompt)</td>
            <td class="bd-num">${fmt(m.prompt_token_count)}</td>
            <td colspan="2" style="font-size:11px;color:var(--muted)">Billable input from Gemini API</td>
            <td class="bd-num cost-cell">${fmtCost(calcInputCost(m.prompt_token_count||0))}</td>
            <td></td>
          </tr>
        ` : `
          <tr>
            <td class="bd-label">Bot Response</td>
            <td class="bd-num">${fmt(m.bot_response_token_count)}</td>
            <td class="bd-num">${fmt(m.bot_response_word_count)}</td>
            <td class="bd-num">${fmt(m.bot_response_char_count)}</td>
            <td class="bd-num cost-cell">${fmtCost(calcOutputCost(m.bot_response_token_count||0))}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.content)||'-'}</div></td>
          </tr>
          <tr style="background:rgba(79,70,229,.06);font-weight:600">
            <td class="bd-label">Total (Completion)</td>
            <td class="bd-num">${fmt(m.completion_token_count)}</td>
            <td colspan="2" style="font-size:11px;color:var(--muted)">Billable output — includes tool call generation + final response</td>
            <td class="bd-num cost-cell">${fmtCost(calcOutputCost(m.completion_token_count||0))}</td>
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
  const files = filterByDate(RAW.files, days);
  const websites = filterByDate(RAW.websites, days);
  const chatMsgs = filterByDate(RAW.chat_messages||[], days);
  const tokenLog = filterByDate(RAW.token_usage_log||[], days);
  const tablesMeta = filterByDate(RAW.tables_metadata||[], days);

  const wb = XLSX.utils.book_new();

  // Sheet 1: Chat Sessions
  const sessData = sessions.map(r => {
    const cost = calcSessionCost(r.total_prompt_token_count||0, r.total_completion_token_count||0);
    return {
      'Session ID': r.id,
      'Started At': r.started_at,
      'Messages': r.message_count||0,
      'Characters': r.total_character_count||0,
      'Words': r.total_word_count||0,
      'Msg Tokens': r.total_message_token_count||0,
      'Prompt Tokens (input)': r.total_prompt_token_count||0,
      'Completion Tokens (output)': r.total_completion_token_count||0,
      'System Prompt Tokens': r.total_system_prompt_token_count||0,
      'History Tokens': r.total_history_token_count||0,
      'Tool Def Tokens': r.total_tool_def_token_count||0,
      'User Msg Tokens': r.total_user_msg_token_count||0,
      'Bot Response Tokens': r.total_bot_response_token_count||0,
      'Est. Input Cost ($)': calcInputCost(r.total_prompt_token_count||0).toFixed(6),
      'Est. Output Cost ($)': calcOutputCost(r.total_completion_token_count||0).toFixed(6),
      'Est. Total Cost ($)': cost.toFixed(6),
      'Duration (min)': r.duration_minutes||'',
      'Status': r.archive_status||'',
      'Sentiment': r.sentiment||''
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sessData), 'Chat Sessions');

  // Sheet 2: Chat Messages
  const msgData = chatMsgs.map(r => {
    const inCost = r.role==='user' ? calcInputCost(r.prompt_token_count||0) : 0;
    const outCost = r.role==='assistant' ? calcOutputCost(r.completion_token_count||0) : 0;
    return {
      'Message ID': r.id,
      'Session ID': r.session_id,
      'Role': r.role==='assistant'?'Bot':r.role==='user'?'User':r.role,
      'Message Content': r.content||'',
      'Characters': r.character_count||0,
      'Words': r.word_count||0,
      'Msg Tokens': r.message_token_count||0,
      'Prompt Tokens': r.prompt_token_count||0,
      'Completion Tokens': r.completion_token_count||0,
      'System Prompt Tokens': r.system_prompt_token_count||0,
      'History Tokens': r.history_token_count||0,
      'Tool Def Tokens': r.tool_def_token_count||0,
      'User Msg Tokens': r.user_msg_token_count||0,
      'Bot Response Tokens': r.bot_response_token_count||0,
      'Est. Cost ($)': (inCost + outCost).toFixed(6),
      'Created': r.created_at||''
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(msgData), 'Chat Messages');

  // Sheet 3: File Uploads
  const fileData = files.map(r => {
    return {
      'Filename': r.original_filename||'',
      'Extension': r.file_extension||'',
      'File Size (bytes)': r.file_size||0,
      'Markdown Chars': r.filestore_character_count||0,
      'Markdown Words': r.filestore_word_count||0,
      'Markdown Tokens': r.filestore_token_count||0,
      'Status': r.processing_status||'',
      'Docling': r.processed_by_docling?'Yes':'No',
      'Created': r.created_at||''
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(fileData), 'File Uploads');

  // Sheet 4: Scraped Websites
  const webData = websites.map(r => {
    return {
      'URL': r.original_url||'',
      'Title': r.title||'',
      'Pages Crawled': r.pages_scraped||0,
      'Markdown Chars': r.filestore_character_count||0,
      'Markdown Words': r.filestore_word_count||0,
      'Markdown Tokens': r.filestore_token_count||0,
      'Status': r.processing_status||'',
      'Depth': r.depth||0,
      'Is Child': r.parent_id?'Yes':'No',
      'Created': r.created_at||''
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(webData), 'Scraped Websites');

  // Sheet 5: Agent Run Steps
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

  // Sheet 6: Table Formatting Detail
  const tablesData = tablesMeta.map(r => {
    const cost = calcTableCost(r.table_input_token_count||0, r.table_output_token_count||0);
    return {
      'Source': r.source_name||'',
      'Source ID': r.file_upload_id || r.scraped_website_id || '',
      'Source Type': r.source_type,
      'Table #': r.table_index,
      'Columns': r.table_column_count_input||0,
      'Rows': r.table_row_count_input||0,
      'Input Chars': r.table_character_count_input||0,
      'Output Chars': r.table_character_count_output||0,
      'Input Tokens': r.table_input_token_count||0,
      'Output Tokens': r.table_output_token_count||0,
      'Est. Cost ($)': cost.toFixed(6),
      'Created': r.created_at||''
    };
  });
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tablesData), 'Table Formatting');

  // excel sheet for token log removed as requested

  // Sheet 8: Cost Summary
  const totalPromptTokens = sessions.reduce((a,r) => a+(r.total_prompt_token_count||0), 0);
  const totalCompletionTokens = sessions.reduce((a,r) => a+(r.total_completion_token_count||0), 0);
  const totalTableIn = tablesMeta.reduce((a,r) => a+(r.table_input_token_count||0), 0);
  const totalTableOut = tablesMeta.reduce((a,r) => a+(r.table_output_token_count||0), 0);
  let totalCacheRead = 0, totalCacheWrite = 0;
  tokenLog.forEach(r => { const c = getCacheTokens(r.request_metadata); totalCacheRead += c.read; totalCacheWrite += c.write; });
  const totalStandardIn = Math.max(0, totalPromptTokens - totalCacheRead);
  const costSummary = [
    {'Category': 'Chat Input (Standard)', 'Tokens': totalStandardIn, 'Rate ($/1M)': 0.10, 'Est. Cost ($)': calcInputCost(totalStandardIn).toFixed(6)},
    {'Category': 'Chat Output (Completion)', 'Tokens': totalCompletionTokens, 'Rate ($/1M)': 0.40, 'Est. Cost ($)': calcOutputCost(totalCompletionTokens).toFixed(6)},
    {'Category': 'Cache Read (90% off)', 'Tokens': totalCacheRead, 'Rate ($/1M)': 0.01, 'Est. Cost ($)': calcCacheReadCost(totalCacheRead).toFixed(6)},
    {'Category': 'Cache Write', 'Tokens': totalCacheWrite, 'Rate ($/1M)': 0.10, 'Est. Cost ($)': calcCacheWriteCost(totalCacheWrite).toFixed(6)},
    {'Category': 'Table Formatting (Input)', 'Tokens': totalTableIn, 'Rate ($/1M)': 0.10, 'Est. Cost ($)': calcInputCost(totalTableIn).toFixed(6)},
    {'Category': 'Table Formatting (Output)', 'Tokens': totalTableOut, 'Rate ($/1M)': 0.40, 'Est. Cost ($)': calcOutputCost(totalTableOut).toFixed(6)},
    {'Category': 'TOTAL ESTIMATED COST', 'Tokens': '', 'Rate ($/1M)': '', 'Est. Cost ($)': (calcInputCost(totalStandardIn) + calcOutputCost(totalCompletionTokens) + calcCacheReadCost(totalCacheRead) + calcCacheWriteCost(totalCacheWrite) + calcTableCost(totalTableIn, totalTableOut)).toFixed(6)},
    {'Category': '', 'Tokens': '', 'Rate ($/1M)': '', 'Est. Cost ($)': ''},
    {'Category': 'NOTE: FileSearch upload/storage costs billed separately by Google (not tracked)', 'Tokens': '', 'Rate ($/1M)': '', 'Est. Cost ($)': ''},
    {'Category': 'NOTE: Cache storage ($1.00/hr/1M tokens) not tracked in this report', 'Tokens': '', 'Rate ($/1M)': '', 'Est. Cost ($)': ''},
    {'Category': 'Pricing: Gemini 2.5 Flash Lite Paid Tier (as of 2025)', 'Tokens': '', 'Rate ($/1M)': '', 'Est. Cost ($)': ''}
  ];
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(costSummary), 'Cost Summary');

  XLSX.writeFile(wb, `usage-report-${days}d-${new Date().toISOString().substring(0,10)}.xlsx`);
}


// === INIT ===
render();
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
