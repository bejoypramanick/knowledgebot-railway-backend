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
                   processed_by_docling, created_at
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

    return {"sessions": sessions, "messages": messages, "files": files, "websites": websites, "chat_messages": chat_messages}


@router.get("/usage", response_class=HTMLResponse)
async def usage_report(request: Request):
    """Single endpoint. All data embedded, JS handles filtering/charts/downloads."""
    data = await _fetch_all_data()
    data_json = json.dumps(data, default=str)

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Usage Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
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
.accent{color:var(--accent)}.green{color:var(--green)}.orange{color:var(--orange)}.cyan{color:var(--cyan)}
.chart-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(580px,1fr));gap:20px;margin-bottom:32px}
.chart-card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px}
.chart-card h3{font-size:15px;margin-bottom:12px;color:var(--muted)}
.chart-card canvas{max-height:300px}
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
<h3>Metric Definitions <span style="font-size:12px;color:var(--muted);font-weight:400;cursor:pointer" onclick="document.getElementById('legend-detail').style.display=document.getElementById('legend-detail').style.display==='none'?'block':'none'">[show/hide]</span></h3>
<div id="legend-detail" class="legend-grid" style="display:none">
  <div class="legend-section">
    <h4>Chat Message Metrics (per message)</h4>
    <dl>
      <dt>Characters</dt><dd>Total characters in the message text, including spaces, punctuation, and emojis</dd>
      <dt>Words</dt><dd>Total words in the message text (split by whitespace)</dd>
      <dt>Msg Tokens</dt><dd>Gemini tokens for ONLY the message text itself (via count_tokens API). A "hi" = ~1 token</dd>
      <dt>Prompt Tokens</dt><dd>Total tokens sent TO Gemini for this turn: system prompt + conversation history + tool definitions + the user message. Only set on user messages. This is the billable input</dd>
      <dt>Completion Tokens</dt><dd>Total tokens generated BY Gemini as the response. Only set on bot messages. This is the billable output</dd>
    </dl>
  </div>
  <div class="legend-section">
    <h4>Prompt Component Breakdown (per user message)</h4>
    <dl>
      <dt>System Prompt</dt><dd>The persona instructions + RAG enforcement rules sent at the start of every turn. Chars/words/tokens counted separately via count_tokens API</dd>
      <dt>History</dt><dd>All prior user + bot messages in the conversation, serialized as text. Grows with each turn. Chars/words/tokens counted separately</dd>
      <dt>Tool Defs</dt><dd>Definitions of tools the agent can call (e.g. FileSearchTool). Relatively static. Chars/words/tokens counted separately</dd>
      <dt>User Msg</dt><dd>Just the current user message text. Chars/words/tokens counted separately. Same as Msg Tokens but stored in dedicated columns</dd>
      <dt>Bot Response</dt><dd>Just the bot's generated response text. Chars/words/tokens stored on the assistant message row</dd>
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
    <h4>File Upload Metrics</h4>
    <dl>
      <dt>File Size</dt><dd>Size of the original uploaded file in bytes</dd>
      <dt>Markdown Chars</dt><dd>Characters in the processed Markdown sent to Gemini FileSearch (after docling conversion + Gemini table formatting)</dd>
      <dt>Markdown Words</dt><dd>Words in the processed Markdown sent to Gemini FileSearch</dd>
      <dt>Markdown Tokens</dt><dd>Gemini tokens for the processed Markdown (via count_tokens API). This is what Gemini indexes for RAG search</dd>
    </dl>
  </div>
  <div class="legend-section">
    <h4>Scraped Website Metrics</h4>
    <dl>
      <dt>Pages</dt><dd>Number of web pages successfully crawled and processed</dd>
      <dt>Markdown Chars</dt><dd>Characters in the processed Markdown sent to Gemini FileSearch (after trafilatura text extraction + Gemini table formatting)</dd>
      <dt>Markdown Words</dt><dd>Words in the processed Markdown sent to Gemini FileSearch</dd>
      <dt>Markdown Tokens</dt><dd>Gemini tokens for the processed Markdown (via count_tokens API). This is what Gemini indexes for RAG search</dd>
    </dl>
  </div>
</div>
</div>

<div class="kpi-grid" id="kpis"></div>

<div class="chart-grid">
  <div class="chart-card"><h3>Daily Message Volume</h3><canvas id="dailyMsgChart"></canvas></div>
  <div class="chart-card"><h3>Daily Token Consumption</h3><canvas id="dailyTokenChart"></canvas></div>
  <div class="chart-card"><h3>Messages by Role</h3><canvas id="roleChart"></canvas></div>
  <div class="chart-card"><h3>Avg Tokens per Message by Role</h3><canvas id="avgTokenChart"></canvas></div>
  <div class="chart-card"><h3>Top 10 Sessions by Token Usage</h3><canvas id="topSessionsChart"></canvas></div>
  <div class="chart-card"><h3>File & Website Token Distribution</h3><canvas id="fileTokenChart"></canvas></div>
</div>

<div class="section"><h2>Chat Sessions <span style="font-size:13px;color:var(--muted);font-weight:400">(click to expand messages)</span></h2><div class="table-wrap" style="max-height:700px"><table>
  <thead><tr><th>Session ID</th><th>Started</th><th title="Total messages (user + bot + human agent) in this session">Msgs</th><th title="Sum of all characters from every message in this session (spaces, punctuation, emojis included)">Chars</th><th title="Sum of all words from every message in this session">Words</th><th title="Sum of Gemini tokens for ONLY the message text of each message (count_tokens API). Represents actual content size">Msg Tokens</th><th title="Sum of total tokens sent TO Gemini across all turns (system prompt + history + tools + user message). This is the billable input">Prompt Tokens</th><th title="Sum of tokens generated BY Gemini across all turns. This is the billable output">Completion Tokens</th><th title="Sum of system prompt tokens across all turns">Sys Prompt Tok</th><th title="Sum of conversation history tokens across all turns">History Tok</th><th title="Sum of tool definition tokens across all turns">Tool Def Tok</th><th title="Sum of user message text tokens across all turns">User Msg Tok</th><th title="Sum of bot response text tokens across all turns">Bot Resp Tok</th><th>Duration</th><th>Status</th></tr></thead>
  <tbody id="sessions-table"></tbody>
</table></div></div>

<div class="section"><h2>File Uploads</h2><div class="table-wrap"><table>
  <thead><tr><th>Filename</th><th>Ext</th><th title="Size of the original uploaded file in bytes">File Size</th><th title="Characters in the processed Markdown sent to Gemini FileSearch (after docling + table formatting)">Markdown Chars</th><th title="Words in the processed Markdown sent to Gemini FileSearch">Markdown Words</th><th title="Gemini tokens for the processed Markdown (count_tokens API) - what Gemini indexes for RAG">Markdown Tokens</th><th>Status</th><th>Date</th></tr></thead>
  <tbody id="files-table"></tbody>
</table></div></div>

<div class="section"><h2>Scraped Websites</h2><div class="table-wrap"><table>
  <thead><tr><th>URL</th><th>Title</th><th title="Number of web pages successfully crawled and processed">Pages</th><th title="Characters in the processed Markdown sent to Gemini FileSearch (after trafilatura + table formatting)">Markdown Chars</th><th title="Words in the processed Markdown sent to Gemini FileSearch">Markdown Words</th><th title="Gemini tokens for the processed Markdown (count_tokens API) - what Gemini indexes for RAG">Markdown Tokens</th><th>Status</th><th>Date</th></tr></thead>
  <tbody id="websites-table"></tbody>
</table></div></div>

</div>

<script>
// === DATA ===
const RAW = """ + data_json + """;
let currentDays = 30;
let charts = {};

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

  document.getElementById('subtitle').textContent =
    `Last ${days} days \u00b7 Generated ${new Date().toISOString().replace('T',' ').substring(0,16)} UTC`;

  // KPIs
  const totalSessions = sessions.length;
  const totalMsgs = sessions.reduce((a,r) => a+(r.message_count||0), 0);
  const totalPromptTokens = sessions.reduce((a,r) => a+(r.total_prompt_token_count||0), 0);
  const totalCompletionTokens = sessions.reduce((a,r) => a+(r.total_completion_token_count||0), 0);
  const totalMsgTokens = sessions.reduce((a,r) => a+(r.total_message_token_count||0), 0);
  const totalChars = sessions.reduce((a,r) => a+(r.total_character_count||0), 0);
  const totalFiles = files.length;
  const fileTokens = files.reduce((a,r) => a+(r.filestore_token_count||0), 0);
  const fileChars = files.reduce((a,r) => a+(r.filestore_character_count||0), 0);
  const totalWebsites = websites.length;
  const webTokens = websites.reduce((a,r) => a+(r.filestore_token_count||0), 0);

  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="label">Total Sessions</div><div class="value accent">${fmt(totalSessions)}</div><div class="sub">${fmt(totalMsgs)} messages total</div></div>
    <div class="kpi"><div class="label">Prompt Tokens (Billable Input)</div><div class="value green">${fmt(totalPromptTokens)}</div><div class="sub">Total tokens sent TO Gemini (system prompt + history + tools + message)</div></div>
    <div class="kpi"><div class="label">Completion Tokens (Billable Output)</div><div class="value cyan">${fmt(totalCompletionTokens)}</div><div class="sub">Total tokens generated BY Gemini as responses</div></div>
    <div class="kpi"><div class="label">Message-Only Tokens</div><div class="value accent">${fmt(totalMsgTokens)}</div><div class="sub">Tokens for just message text (${fmt(totalChars)} characters)</div></div>
    <div class="kpi"><div class="label">Files Uploaded</div><div class="value orange">${fmt(totalFiles)}</div><div class="sub">${fmt(fileTokens)} markdown tokens indexed</div></div>
    <div class="kpi"><div class="label">Websites Scraped</div><div class="value green">${fmt(totalWebsites)}</div><div class="sub">${fmt(webTokens)} markdown tokens indexed</div></div>
  `;

  // Daily chart data
  const dailyMap = {};
  messages.forEach(r => {
    const d = r.day;
    if(!dailyMap[d]) dailyMap[d]={userMsgs:0,botMsgs:0,userTokens:0,botTokens:0};
    if(r.role==='user'){dailyMap[d].userMsgs=r.msg_count;dailyMap[d].userTokens=r.total_tokens}
    else if(r.role==='assistant'){dailyMap[d].botMsgs=r.msg_count;dailyMap[d].botTokens=r.total_tokens}
  });
  const dLabels=Object.keys(dailyMap), dUserM=dLabels.map(k=>dailyMap[k].userMsgs), dBotM=dLabels.map(k=>dailyMap[k].botMsgs);
  const dUserT=dLabels.map(k=>dailyMap[k].userTokens), dBotT=dLabels.map(k=>dailyMap[k].botTokens);

  // Role breakdown
  const roleMap = {};
  messages.forEach(r => {
    if(!roleMap[r.role]) roleMap[r.role]={count:0,tokens:0,chars:0,words:0,avgTokens:0,n:0};
    const rm=roleMap[r.role]; rm.count+=r.msg_count; rm.tokens+=r.total_tokens; rm.chars+=r.total_chars; rm.words+=r.total_words;
    rm.avgTokens=((rm.avgTokens*rm.n)+r.avg_tokens)/(rm.n+1); rm.n++;
  });
  const rLabels=Object.keys(roleMap), rCounts=rLabels.map(k=>roleMap[k].count), rAvgT=rLabels.map(k=>Math.round(roleMap[k].avgTokens));

  // Top sessions
  const topS = [...sessions].filter(r=>r.total_token_count>0).sort((a,b)=>(b.total_token_count||0)-(a.total_token_count||0)).slice(0,10);
  const tLabels=topS.map(r=>String(r.id).substring(0,8)+'...'), tTokens=topS.map(r=>r.total_token_count||0), tWords=topS.map(r=>r.total_word_count||0);

  // File+Website tokens combined
  const fsItems = [
    ...files.filter(r=>r.filestore_token_count>0).map(r=>({name:trunc(r.original_filename,25),tokens:r.filestore_token_count,type:'file'})),
    ...websites.filter(r=>r.filestore_token_count>0).map(r=>({name:trunc(r.original_url,30),tokens:r.filestore_token_count,type:'web'}))
  ].sort((a,b)=>b.tokens-a.tokens).slice(0,15);
  const fLabels=fsItems.map(r=>r.name), fTokens=fsItems.map(r=>r.tokens);
  const fColors=fsItems.map(r=>r.type==='file'?'rgba(249,115,22,.7)':'rgba(6,182,212,.7)');

  // === CHARTS ===
  Object.values(charts).forEach(c=>c.destroy());
  charts={};

  Chart.defaults.color='#9ca3af'; Chart.defaults.borderColor='#2a2d3a';

  charts.dailyMsg = new Chart(document.getElementById('dailyMsgChart'),{type:'bar',data:{labels:dLabels,datasets:[
    {label:'User Messages',data:dUserM,backgroundColor:'rgba(99,102,241,.7)',borderRadius:4},
    {label:'Bot Responses',data:dBotM,backgroundColor:'rgba(34,197,94,.7)',borderRadius:4}
  ]},options:{responsive:true,plugins:{legend:{position:'top'}},scales:{y:{beginAtZero:true}}}});

  charts.dailyToken = new Chart(document.getElementById('dailyTokenChart'),{type:'line',data:{labels:dLabels,datasets:[
    {label:'Input Tokens (User)',data:dUserT,borderColor:'#6366f1',backgroundColor:'rgba(99,102,241,.1)',fill:true,tension:.3},
    {label:'Output Tokens (Bot)',data:dBotT,borderColor:'#22c55e',backgroundColor:'rgba(34,197,94,.1)',fill:true,tension:.3}
  ]},options:{responsive:true,plugins:{legend:{position:'top'}},scales:{y:{beginAtZero:true}}}});

  charts.role = new Chart(document.getElementById('roleChart'),{type:'doughnut',data:{labels:rLabels,datasets:[
    {data:rCounts,backgroundColor:['#6366f1','#22c55e','#f97316','#06b6d4','#ec4899']}
  ]},options:{responsive:true,plugins:{legend:{position:'right'}}}});

  charts.avgToken = new Chart(document.getElementById('avgTokenChart'),{type:'bar',data:{labels:rLabels,datasets:[
    {label:'Avg Tokens',data:rAvgT,backgroundColor:['#8b5cf6','#06b6d4','#f97316','#22c55e','#ec4899'],borderRadius:6}
  ]},options:{responsive:true,indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true}}}});

  charts.topSessions = new Chart(document.getElementById('topSessionsChart'),{type:'bar',data:{labels:tLabels,datasets:[
    {label:'Tokens',data:tTokens,backgroundColor:'rgba(99,102,241,.8)',borderRadius:4},
    {label:'Words',data:tWords,backgroundColor:'rgba(6,182,212,.6)',borderRadius:4}
  ]},options:{responsive:true,plugins:{legend:{position:'top'}},scales:{y:{beginAtZero:true}}}});

  charts.fileToken = new Chart(document.getElementById('fileTokenChart'),{type:'bar',data:{labels:fLabels,datasets:[
    {label:'Filestore Tokens',data:fTokens,backgroundColor:fColors,borderRadius:4}
  ]},options:{responsive:true,indexAxis:'y',plugins:{legend:{display:false}},scales:{x:{beginAtZero:true}}}});

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
  // Sort messages within each session by created_at ascending (chronological)
  Object.values(msgBySession).forEach(arr => arr.sort((a,b) => (a.created_at||'').localeCompare(b.created_at||'')));

  // === SESSIONS TABLE (expandable) ===
  const sessionsEl = document.getElementById('sessions-table');
  sessionsEl.innerHTML = '';
  sessions.slice(0,100).forEach(r => {
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
      <td>${r.duration_minutes||'-'}</td>
      <td>${badge(r.archive_status)}</td>`;
    sessionRow.onclick = function() { toggleSession(this, r.id); };
    sessionsEl.appendChild(sessionRow);
  });

  // === OTHER TABLES ===
  document.getElementById('files-table').innerHTML = files.slice(0,100).map(r=>`<tr>
    <td title="${r.original_filename}">${trunc(r.original_filename,35)}</td><td>${r.file_extension||'-'}</td>
    <td>${fmt(r.file_size)}</td><td>${fmt(r.filestore_character_count)}</td><td>${fmt(r.filestore_word_count)}</td>
    <td class="token-cell">${fmt(r.filestore_token_count)}</td><td>${badge(r.processing_status)}</td>
    <td>${fmtDate(r.created_at)}</td></tr>`).join('');

  document.getElementById('websites-table').innerHTML = websites.slice(0,100).map(r=>`<tr>
    <td title="${r.original_url}">${trunc(r.original_url,40)}${r.parent_id?' (child)':''}</td>
    <td>${trunc(r.title,30)}</td><td>${r.pages_scraped||0}</td>
    <td>${fmt(r.filestore_character_count)}</td><td>${fmt(r.filestore_word_count)}</td>
    <td class="token-cell">${fmt(r.filestore_token_count)}</td><td>${badge(r.processing_status)}</td>
    <td>${fmtDate(r.created_at)}</td></tr>`).join('');
}

// === EXPAND/COLLAPSE SESSION MESSAGES ===
function toggleSession(rowEl, sessionId) {
  const isOpen = rowEl.classList.contains('open');

  // Remove any existing expanded message rows for this session
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
    emptyRow.innerHTML = `<td colspan="15" style="color:var(--muted);font-style:italic;padding-left:32px">No messages found for this session</td>`;
    rowEl.after(emptyRow);
    return;
  }

  const roleName = r => r==='assistant'?'Bot':r==='user'?'User':r==='human_agent'?'Human Agent':(r||'Unknown');
  const escHtml = s => s ? s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;') : '-';

  // Insert message rows chronologically with merged-cell breakdown
  let insertAfter = rowEl;
  msgs.forEach((m, idx) => {
    // === Main message row ===
    const msgRow = document.createElement('tr');
    msgRow.className = 'msg-row';
    msgRow.innerHTML = `<td colspan="15" style="padding-left:24px">
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
            <td class="bd-label">Tool Definitions</td>
            <td class="bd-num">${fmt(m.tool_def_token_count)}</td>
            <td class="bd-num">${fmt(m.tool_def_word_count)}</td>
            <td class="bd-num">${fmt(m.tool_def_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.tool_def_text)||'-'}</div></td>
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
            <td colspan="3" style="font-size:11px;color:var(--muted)">= sys prompt + history + tools + user msg (billable input)</td>
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
            <td colspan="3" style="font-size:11px;color:var(--muted)">= Gemini output tokens (billable output)</td>
          </tr>
        `}
        </tbody>
      </table>
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

  const wb = XLSX.utils.book_new();

  // Sheet 1: Chat Sessions
  const sessData = sessions.map(r => ({
    'Session ID': r.id,
    'Started At': r.started_at,
    'Messages': r.message_count||0,
    'Characters (sum of all message chars)': r.total_character_count||0,
    'Words (sum of all message words)': r.total_word_count||0,
    'Msg Tokens (message text only)': r.total_message_token_count||0,
    'Prompt Tokens (billable input to Gemini)': r.total_prompt_token_count||0,
    'Completion Tokens (billable output from Gemini)': r.total_completion_token_count||0,
    'System Prompt Tokens (per-turn sum)': r.total_system_prompt_token_count||0,
    'History Tokens (per-turn sum)': r.total_history_token_count||0,
    'Tool Def Tokens (per-turn sum)': r.total_tool_def_token_count||0,
    'User Msg Tokens (per-turn sum)': r.total_user_msg_token_count||0,
    'Bot Response Tokens (per-turn sum)': r.total_bot_response_token_count||0,
    'Duration (min)': r.duration_minutes||'',
    'Status': r.archive_status||'',
    'Sentiment': r.sentiment||''
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(sessData), 'Chat Sessions');

  // Sheet 2: Chat Messages
  const msgData = chatMsgs.map(r => ({
    'Message ID': r.id,
    'Session ID': r.session_id,
    'Role': r.role==='assistant'?'Bot':r.role==='user'?'User':r.role==='human_agent'?'Human Agent':r.role,
    'Message Content': r.content||'',
    'Characters (in this message)': r.character_count||0,
    'Words (in this message)': r.word_count||0,
    'Msg Tokens (this message text only, count_tokens API)': r.message_token_count||0,
    'Prompt Tokens (full context sent TO Gemini, user msgs only)': r.prompt_token_count||0,
    'Completion Tokens (generated BY Gemini, bot msgs only)': r.completion_token_count||0,
    'System Prompt Chars': r.system_prompt_char_count||0,
    'System Prompt Words': r.system_prompt_word_count||0,
    'System Prompt Tokens': r.system_prompt_token_count||0,
    'History Chars': r.history_char_count||0,
    'History Words': r.history_word_count||0,
    'History Tokens': r.history_token_count||0,
    'Tool Def Chars': r.tool_def_char_count||0,
    'Tool Def Words': r.tool_def_word_count||0,
    'Tool Def Tokens': r.tool_def_token_count||0,
    'User Msg Chars': r.user_msg_char_count||0,
    'User Msg Words': r.user_msg_word_count||0,
    'User Msg Tokens': r.user_msg_token_count||0,
    'Bot Response Chars': r.bot_response_char_count||0,
    'Bot Response Words': r.bot_response_word_count||0,
    'Bot Response Tokens': r.bot_response_token_count||0,
    'Created': r.created_at||''
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(msgData), 'Chat Messages');

  // Sheet 3: File Uploads
  const fileData = files.map(r => ({
    'Filename': r.original_filename||'',
    'Extension': r.file_extension||'',
    'File Size (bytes)': r.file_size||0,
    'Markdown Chars (processed content sent to Gemini FileSearch)': r.filestore_character_count||0,
    'Markdown Words (processed content sent to Gemini FileSearch)': r.filestore_word_count||0,
    'Markdown Tokens (count_tokens API, indexed for RAG)': r.filestore_token_count||0,
    'Status': r.processing_status||'',
    'Processed by Docling': r.processed_by_docling?'Yes':'No',
    'Created': r.created_at||''
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(fileData), 'File Uploads');

  // Sheet 4: Scraped Websites
  const webData = websites.map(r => ({
    'URL': r.original_url||'',
    'Title': r.title||'',
    'Pages Crawled': r.pages_scraped||0,
    'Markdown Chars (processed content sent to Gemini FileSearch)': r.filestore_character_count||0,
    'Markdown Words (processed content sent to Gemini FileSearch)': r.filestore_word_count||0,
    'Markdown Tokens (count_tokens API, indexed for RAG)': r.filestore_token_count||0,
    'Status': r.processing_status||'',
    'Depth': r.depth||0,
    'Is Child Page': r.parent_id?'Yes':'No',
    'Created': r.created_at||''
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(webData), 'Scraped Websites');

  XLSX.writeFile(wb, `usage-report-${days}d-${new Date().toISOString().substring(0,10)}.xlsx`);
}


// === INIT ===
render();
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
