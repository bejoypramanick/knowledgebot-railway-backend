"""
Usage Report - Single Endpoint
GET /reports/usage → self-contained HTML report.
All filtering, CSV download, PDF download handled client-side.
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

    return {"sessions": sessions, "messages": messages, "files": files, "websites": websites}


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
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
:root {
  --bg:#0f1117;--card:#1a1d27;--border:#2a2d3a;--text:#e4e4e7;
  --muted:#9ca3af;--accent:#6366f1;--accent2:#8b5cf6;--green:#22c55e;
  --orange:#f97316;--red:#ef4444;--blue:#3b82f6;--cyan:#06b6d4;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);padding:24px}
.container{max-width:1400px;margin:0 auto}
h1{font-size:28px;margin-bottom:4px}
.subtitle{color:var(--muted);margin-bottom:24px;font-size:14px}
.toolbar{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap;align-items:center}
.toolbar button,.toolbar select{padding:8px 16px;border-radius:8px;font-size:13px;cursor:pointer;border:1px solid var(--border);background:var(--card);color:var(--text);transition:.2s}
.toolbar button:hover{border-color:var(--accent);background:#23263a}
.toolbar .active{border-color:var(--accent);background:rgba(99,102,241,.15);color:var(--accent)}
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
tr:hover td{background:rgba(99,102,241,.05)}
.mono{font-family:'SF Mono','Fira Code',monospace;font-size:12px}
.token-cell{font-weight:600;color:var(--accent)}
.badge{padding:3px 8px;border-radius:6px;font-size:11px;font-weight:600}
.badge-active,.badge-completed{background:rgba(34,197,94,.15);color:var(--green)}
.badge-closed,.badge-archived{background:rgba(156,163,175,.15);color:var(--muted)}
.badge-processing,.badge-pending{background:rgba(249,115,22,.15);color:var(--orange)}
.badge-failed,.badge-cancelled,.badge-deleted{background:rgba(239,68,68,.15);color:var(--red)}
.loading{text-align:center;padding:40px;color:var(--muted)}
.table-wrap{overflow-x:auto;max-height:500px;overflow-y:auto;border:1px solid var(--border);border-radius:8px}
@media print{
  body{background:#fff;color:#1a1a1a;padding:12px}
  .toolbar{display:none}
  .kpi,.chart-card{border:1px solid #ddd;background:#fff}
  .kpi .value{color:#1a1a1a}
  .accent,.token-cell{color:#4f46e5!important}
  th{background:#f5f5f5}td{border-color:#eee}
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
  <button onclick="downloadCSV()">Download CSV</button>
  <button onclick="downloadPDF()">Download PDF</button>
  <button onclick="window.print()">Print</button>
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

<div class="section"><h2>Chat Sessions</h2><div class="table-wrap"><table>
  <thead><tr><th>Session ID</th><th>Started</th><th>Messages</th><th>Characters</th><th>Words</th><th>Tokens</th><th>Duration</th><th>Status</th></tr></thead>
  <tbody id="sessions-table"></tbody>
</table></div></div>

<div class="section"><h2>File Uploads</h2><div class="table-wrap"><table>
  <thead><tr><th>Filename</th><th>Ext</th><th>File Size</th><th>FS Chars</th><th>FS Words</th><th>FS Tokens</th><th>Status</th><th>Date</th></tr></thead>
  <tbody id="files-table"></tbody>
</table></div></div>

<div class="section"><h2>Scraped Websites</h2><div class="table-wrap"><table>
  <thead><tr><th>URL</th><th>Title</th><th>Pages</th><th>FS Chars</th><th>FS Words</th><th>FS Tokens</th><th>Status</th><th>Date</th></tr></thead>
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
  const totalTokens = sessions.reduce((a,r) => a+(r.total_token_count||0), 0);
  const totalChars = sessions.reduce((a,r) => a+(r.total_character_count||0), 0);
  const totalWords = sessions.reduce((a,r) => a+(r.total_word_count||0), 0);
  const totalFiles = files.length;
  const fileTokens = files.reduce((a,r) => a+(r.filestore_token_count||0), 0);
  const fileChars = files.reduce((a,r) => a+(r.filestore_character_count||0), 0);
  const totalWebsites = websites.length;
  const webTokens = websites.reduce((a,r) => a+(r.filestore_token_count||0), 0);

  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="label">Total Sessions</div><div class="value accent">${fmt(totalSessions)}</div><div class="sub">${fmt(totalMsgs)} messages</div></div>
    <div class="kpi"><div class="label">Chat Tokens</div><div class="value green">${fmt(totalTokens)}</div><div class="sub">${fmt(totalChars)} characters</div></div>
    <div class="kpi"><div class="label">Chat Words</div><div class="value cyan">${fmt(totalWords)}</div><div class="sub">across all sessions</div></div>
    <div class="kpi"><div class="label">Files Uploaded</div><div class="value orange">${fmt(totalFiles)}</div><div class="sub">${fmt(fileTokens)} filestore tokens</div></div>
    <div class="kpi"><div class="label">File Characters</div><div class="value accent">${fmt(fileChars)}</div><div class="sub">markdown sent to Gemini</div></div>
    <div class="kpi"><div class="label">Websites Scraped</div><div class="value green">${fmt(totalWebsites)}</div><div class="sub">${fmt(webTokens)} filestore tokens</div></div>
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

  // === TABLES ===
  document.getElementById('sessions-table').innerHTML = sessions.slice(0,100).map(r=>`<tr>
    <td class="mono">${String(r.id).substring(0,8)}...</td>
    <td>${fmtDateTime(r.started_at)}</td><td>${r.message_count||0}</td>
    <td>${fmt(r.total_character_count)}</td><td>${fmt(r.total_word_count)}</td>
    <td class="token-cell">${fmt(r.total_token_count)}</td><td>${r.duration_minutes||'-'}</td>
    <td>${badge(r.archive_status)}</td></tr>`).join('');

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

// === CSV DOWNLOAD (client-side) ===
function downloadCSV() {
  const days = currentDays;
  const sessions = filterByDate(RAW.sessions, days);
  const files = filterByDate(RAW.files, days);
  const websites = filterByDate(RAW.websites, days);
  const messages = filterByDate(RAW.messages, days, 'day');

  let csv = '';
  const row = arr => csv += arr.map(v => `"${String(v??'').replace(/"/g,'""')}"`).join(',') + '\\n';

  row(['=== CHAT SESSIONS ===']);
  row(['Session ID','Started At','Messages','Characters','Words','Tokens','Duration (min)','Status','Sentiment']);
  sessions.forEach(r => row([r.id,r.started_at,r.message_count,r.total_character_count,r.total_word_count,r.total_token_count,r.duration_minutes,r.archive_status,r.sentiment]));

  row([]); row(['=== MESSAGE BREAKDOWN BY ROLE ===']);
  row(['Day','Role','Message Count','Total Characters','Total Words','Total Tokens','Avg Chars','Avg Words','Avg Tokens']);
  messages.forEach(r => row([r.day,r.role,r.msg_count,r.total_chars,r.total_words,r.total_tokens,Math.round(r.avg_chars),Math.round(r.avg_words),Math.round(r.avg_tokens)]));

  row([]); row(['=== FILE UPLOADS ===']);
  row(['Filename','Extension','File Size','FS Characters','FS Words','FS Tokens','Status','Docling','Created']);
  files.forEach(r => row([r.original_filename,r.file_extension,r.file_size,r.filestore_character_count,r.filestore_word_count,r.filestore_token_count,r.processing_status,r.processed_by_docling,r.created_at]));

  row([]); row(['=== SCRAPED WEBSITES ===']);
  row(['URL','Title','Pages','FS Characters','FS Words','FS Tokens','Status','Depth','Is Child','Created']);
  websites.forEach(r => row([r.original_url,r.title,r.pages_scraped,r.filestore_character_count,r.filestore_word_count,r.filestore_token_count,r.processing_status,r.depth,r.parent_id?'Yes':'No',r.created_at]));

  const blob = new Blob([csv], {type:'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `usage-report-${days}d-${new Date().toISOString().substring(0,10)}.csv`;
  a.click();
}

// === PDF DOWNLOAD ===
function downloadPDF() {
  const el = document.getElementById('report-content');
  html2pdf().set({
    margin:[10,10,10,10],
    filename:`usage-report-${currentDays}d.pdf`,
    image:{type:'jpeg',quality:.98},
    html2canvas:{scale:2,useCORS:true,backgroundColor:'#0f1117'},
    jsPDF:{unit:'mm',format:'a3',orientation:'landscape'},
    pagebreak:{mode:['avoid-all','css','legacy']}
  }).from(el).save();
}

// === INIT ===
render();
</script>
</body>
</html>"""

    return HTMLResponse(content=html)
