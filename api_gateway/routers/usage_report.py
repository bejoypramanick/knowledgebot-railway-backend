"""
Usage Report Endpoint
Generates an HTML report with charts for usage tracking metrics.
Protected by session auth middleware.
Supports: HTML view, PDF download, CSV download.
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from typing import Optional
import io
import csv
from datetime import datetime, timedelta

from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from sqlalchemy import text

logger = get_otel_logger("usage_report", "api-gateway")

router = APIRouter(prefix="/reports", tags=["reports"])


async def _fetch_report_data(days: int = 30):
    """Fetch all usage data from PG for the report."""
    since = datetime.utcnow() - timedelta(days=days)

    async with get_db_session() as db:
        # 1. Session-level aggregates
        sessions = (await db.execute(text("""
            SELECT id, started_at, last_activity_at, message_count,
                   total_character_count, total_word_count, total_token_count,
                   archive_status, sentiment, duration_minutes
            FROM chat_sessions
            WHERE created_at >= :since
            ORDER BY created_at DESC
        """), {"since": since})).fetchall()

        # 2. Message-level breakdown (aggregated by role)
        msg_by_role = (await db.execute(text("""
            SELECT role,
                   COUNT(*) as msg_count,
                   COALESCE(SUM(character_count), 0) as total_chars,
                   COALESCE(SUM(word_count), 0) as total_words,
                   COALESCE(SUM(token_count), 0) as total_tokens,
                   COALESCE(AVG(character_count), 0) as avg_chars,
                   COALESCE(AVG(word_count), 0) as avg_words,
                   COALESCE(AVG(token_count), 0) as avg_tokens
            FROM chat_messages
            WHERE created_at >= :since
            GROUP BY role
            ORDER BY role
        """), {"since": since})).fetchall()

        # 3. Daily message volume & tokens
        daily_msgs = (await db.execute(text("""
            SELECT DATE(created_at) as day,
                   role,
                   COUNT(*) as msg_count,
                   COALESCE(SUM(token_count), 0) as total_tokens,
                   COALESCE(SUM(character_count), 0) as total_chars
            FROM chat_messages
            WHERE created_at >= :since
            GROUP BY DATE(created_at), role
            ORDER BY day
        """), {"since": since})).fetchall()

        # 4. File uploads with filestore metrics
        files = (await db.execute(text("""
            SELECT id, original_filename, display_name, file_extension, processing_status,
                   file_size, char_count,
                   filestore_character_count, filestore_word_count, filestore_token_count,
                   processed_by_docling, created_at
            FROM file_uploads
            WHERE created_at >= :since
            ORDER BY created_at DESC
        """), {"since": since})).fetchall()

        # 5. Scraped websites with filestore metrics
        websites = (await db.execute(text("""
            SELECT id, original_url, title, processing_status, pages_scraped,
                   file_size, char_count,
                   filestore_character_count, filestore_word_count, filestore_token_count,
                   parent_id, depth, created_at
            FROM scraped_websites
            WHERE created_at >= :since
            ORDER BY created_at DESC
        """), {"since": since})).fetchall()

        # 6. Top sessions by token usage
        top_sessions = (await db.execute(text("""
            SELECT id, started_at, message_count,
                   total_character_count, total_word_count, total_token_count,
                   duration_minutes
            FROM chat_sessions
            WHERE created_at >= :since AND total_token_count > 0
            ORDER BY total_token_count DESC
            LIMIT 10
        """), {"since": since})).fetchall()

        # 7. Summary stats
        summary = (await db.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM chat_sessions WHERE created_at >= :since) as total_sessions,
                (SELECT COUNT(*) FROM chat_messages WHERE created_at >= :since) as total_messages,
                (SELECT COALESCE(SUM(total_token_count), 0) FROM chat_sessions WHERE created_at >= :since) as total_session_tokens,
                (SELECT COALESCE(SUM(total_character_count), 0) FROM chat_sessions WHERE created_at >= :since) as total_session_chars,
                (SELECT COALESCE(SUM(total_word_count), 0) FROM chat_sessions WHERE created_at >= :since) as total_session_words,
                (SELECT COUNT(*) FROM file_uploads WHERE created_at >= :since) as total_files,
                (SELECT COALESCE(SUM(filestore_token_count), 0) FROM file_uploads WHERE created_at >= :since) as total_file_tokens,
                (SELECT COALESCE(SUM(filestore_character_count), 0) FROM file_uploads WHERE created_at >= :since) as total_file_chars,
                (SELECT COUNT(*) FROM scraped_websites WHERE created_at >= :since) as total_websites,
                (SELECT COALESCE(SUM(filestore_token_count), 0) FROM scraped_websites WHERE created_at >= :since) as total_website_tokens,
                (SELECT COALESCE(SUM(filestore_character_count), 0) FROM scraped_websites WHERE created_at >= :since) as total_website_chars
        """), {"since": since})).fetchone()

    return {
        "sessions": sessions,
        "msg_by_role": msg_by_role,
        "daily_msgs": daily_msgs,
        "files": files,
        "websites": websites,
        "top_sessions": top_sessions,
        "summary": summary,
        "days": days,
        "generated_at": datetime.utcnow().isoformat()
    }


def _format_number(n) -> str:
    """Format number with commas."""
    if n is None:
        return "0"
    return f"{int(n):,}"


def _build_daily_chart_data(daily_msgs):
    """Build daily chart data grouped by date."""
    days_map = {}
    for row in daily_msgs:
        day = str(row.day)
        if day not in days_map:
            days_map[day] = {"user_msgs": 0, "bot_msgs": 0, "user_tokens": 0, "bot_tokens": 0, "user_chars": 0, "bot_chars": 0}
        if row.role == "user":
            days_map[day]["user_msgs"] = row.msg_count
            days_map[day]["user_tokens"] = row.total_tokens
            days_map[day]["user_chars"] = row.total_chars
        elif row.role == "assistant":
            days_map[day]["bot_msgs"] = row.msg_count
            days_map[day]["bot_tokens"] = row.total_tokens
            days_map[day]["bot_chars"] = row.total_chars
    return days_map


@router.get("/usage")
async def usage_report(request: Request, days: int = Query(default=30, ge=1, le=365), format: str = Query(default="html")):
    """Single endpoint for usage report. format=html (default) or format=csv."""
    data = await _fetch_report_data(days)

    if format == "csv":
        return _generate_csv(data, days)

    # HTML report
    s = data["summary"]
    daily = _build_daily_chart_data(data["daily_msgs"])

    # Prepare chart data as JSON-safe strings
    import json
    daily_labels = json.dumps(list(daily.keys()))
    daily_user_msgs = json.dumps([v["user_msgs"] for v in daily.values()])
    daily_bot_msgs = json.dumps([v["bot_msgs"] for v in daily.values()])
    daily_user_tokens = json.dumps([v["user_tokens"] for v in daily.values()])
    daily_bot_tokens = json.dumps([v["bot_tokens"] for v in daily.values()])

    # Top sessions data
    top_labels = json.dumps([str(r.id)[:8] + "..." for r in data["top_sessions"]])
    top_tokens = json.dumps([r.total_token_count or 0 for r in data["top_sessions"]])
    top_chars = json.dumps([r.total_character_count or 0 for r in data["top_sessions"]])
    top_words = json.dumps([r.total_word_count or 0 for r in data["top_sessions"]])

    # Message role breakdown
    role_labels = json.dumps([r.role for r in data["msg_by_role"]])
    role_counts = json.dumps([r.msg_count for r in data["msg_by_role"]])
    role_tokens = json.dumps([int(r.total_tokens) for r in data["msg_by_role"]])
    role_avg_tokens = json.dumps([round(float(r.avg_tokens), 1) for r in data["msg_by_role"]])

    # File & website token distribution
    file_names = json.dumps([r.original_filename[:25] + ("..." if len(r.original_filename) > 25 else "") for r in data["files"] if r.filestore_token_count and r.filestore_token_count > 0][:15])
    file_tokens = json.dumps([r.filestore_token_count or 0 for r in data["files"] if r.filestore_token_count and r.filestore_token_count > 0][:15])

    website_names = json.dumps([r.original_url[:30] + ("..." if len(r.original_url) > 30 else "") for r in data["websites"] if r.filestore_token_count and r.filestore_token_count > 0][:15])
    website_tokens = json.dumps([r.filestore_token_count or 0 for r in data["websites"] if r.filestore_token_count and r.filestore_token_count > 0][:15])

    # Sessions table rows
    sessions_rows = ""
    for row in data["sessions"][:50]:
        sessions_rows += f"""<tr>
            <td class="mono">{str(row.id)[:8]}...</td>
            <td>{row.started_at.strftime('%Y-%m-%d %H:%M') if row.started_at else '-'}</td>
            <td>{row.message_count or 0}</td>
            <td>{_format_number(row.total_character_count)}</td>
            <td>{_format_number(row.total_word_count)}</td>
            <td class="token-cell">{_format_number(row.total_token_count)}</td>
            <td>{row.duration_minutes or '-'}</td>
            <td><span class="badge badge-{row.archive_status or 'active'}">{row.archive_status or 'active'}</span></td>
        </tr>"""

    # Files table rows
    files_rows = ""
    for row in data["files"][:50]:
        files_rows += f"""<tr>
            <td title="{row.original_filename}">{row.original_filename[:35]}{'...' if len(row.original_filename) > 35 else ''}</td>
            <td>{row.file_extension or '-'}</td>
            <td>{_format_number(row.file_size)}</td>
            <td>{_format_number(row.filestore_character_count)}</td>
            <td>{_format_number(row.filestore_word_count)}</td>
            <td class="token-cell">{_format_number(row.filestore_token_count)}</td>
            <td><span class="badge badge-{row.processing_status}">{row.processing_status}</span></td>
            <td>{row.created_at.strftime('%Y-%m-%d') if row.created_at else '-'}</td>
        </tr>"""

    # Websites table rows
    websites_rows = ""
    for row in data["websites"][:50]:
        is_child = " (child)" if row.parent_id else ""
        websites_rows += f"""<tr>
            <td title="{row.original_url}">{row.original_url[:40]}{'...' if len(row.original_url) > 40 else ''}{is_child}</td>
            <td>{row.title[:30] if row.title else '-'}{'...' if row.title and len(row.title) > 30 else ''}</td>
            <td>{row.pages_scraped or 0}</td>
            <td>{_format_number(row.filestore_character_count)}</td>
            <td>{_format_number(row.filestore_word_count)}</td>
            <td class="token-cell">{_format_number(row.filestore_token_count)}</td>
            <td><span class="badge badge-{row.processing_status}">{row.processing_status}</span></td>
            <td>{row.created_at.strftime('%Y-%m-%d') if row.created_at else '-'}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Usage Report - Last {days} Days</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2pdf.js/0.10.1/html2pdf.bundle.min.js"></script>
<style>
  :root {{
    --bg: #0f1117; --card: #1a1d27; --border: #2a2d3a; --text: #e4e4e7;
    --muted: #9ca3af; --accent: #6366f1; --accent2: #8b5cf6; --green: #22c55e;
    --orange: #f97316; --red: #ef4444; --blue: #3b82f6; --cyan: #06b6d4;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 24px; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  h1 {{ font-size: 28px; margin-bottom: 4px; }}
  .subtitle {{ color: var(--muted); margin-bottom: 24px; font-size: 14px; }}
  .toolbar {{ display: flex; gap: 10px; margin-bottom: 24px; flex-wrap: wrap; align-items: center; }}
  .toolbar a, .toolbar button {{ padding: 8px 16px; border-radius: 8px; text-decoration: none; font-size: 13px; cursor: pointer; border: 1px solid var(--border); background: var(--card); color: var(--text); transition: 0.2s; }}
  .toolbar a:hover, .toolbar button:hover {{ border-color: var(--accent); background: #23263a; }}
  .toolbar select {{ padding: 8px 12px; border-radius: 8px; background: var(--card); color: var(--text); border: 1px solid var(--border); font-size: 13px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
  .kpi .label {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
  .kpi .value {{ font-size: 28px; font-weight: 700; }}
  .kpi .value.accent {{ color: var(--accent); }}
  .kpi .value.green {{ color: var(--green); }}
  .kpi .value.orange {{ color: var(--orange); }}
  .kpi .value.cyan {{ color: var(--cyan); }}
  .kpi .sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(580px, 1fr)); gap: 20px; margin-bottom: 32px; }}
  .chart-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
  .chart-card h3 {{ font-size: 15px; margin-bottom: 12px; color: var(--muted); }}
  .chart-card canvas {{ max-height: 300px; }}
  .section {{ margin-bottom: 32px; }}
  .section h2 {{ font-size: 20px; margin-bottom: 16px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; padding: 10px 12px; background: var(--card); border-bottom: 2px solid var(--border); color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 11px; letter-spacing: 0.5px; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); }}
  tr:hover td {{ background: rgba(99, 102, 241, 0.05); }}
  .mono {{ font-family: 'SF Mono', 'Fira Code', monospace; font-size: 12px; }}
  .token-cell {{ font-weight: 600; color: var(--accent); }}
  .badge {{ padding: 3px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }}
  .badge-active, .badge-completed {{ background: rgba(34,197,94,0.15); color: var(--green); }}
  .badge-closed, .badge-archived {{ background: rgba(156,163,175,0.15); color: var(--muted); }}
  .badge-processing, .badge-pending {{ background: rgba(249,115,22,0.15); color: var(--orange); }}
  .badge-failed, .badge-cancelled, .badge-deleted {{ background: rgba(239,68,68,0.15); color: var(--red); }}
  @media print {{
    body {{ background: #fff; color: #1a1a1a; padding: 12px; }}
    .toolbar {{ display: none; }}
    .kpi, .chart-card {{ border: 1px solid #ddd; background: #fff; }}
    .kpi .value {{ color: #1a1a1a; }}
    .kpi .value.accent, .token-cell {{ color: #4f46e5; }}
    th {{ background: #f5f5f5; }}
    td {{ border-color: #eee; }}
  }}
</style>
</head>
<body>
<div class="container" id="report-content">

<h1>Usage Report</h1>
<p class="subtitle">Last {days} days &middot; Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>

<div class="toolbar">
  <select onchange="window.location.href='/api/v1/gateway/reports/usage?days='+this.value">
    <option value="7" {"selected" if days==7 else ""}>Last 7 days</option>
    <option value="14" {"selected" if days==14 else ""}>Last 14 days</option>
    <option value="30" {"selected" if days==30 else ""}>Last 30 days</option>
    <option value="90" {"selected" if days==90 else ""}>Last 90 days</option>
    <option value="180" {"selected" if days==180 else ""}>Last 180 days</option>
    <option value="365" {"selected" if days==365 else ""}>Last 365 days</option>
  </select>
  <a href="/api/v1/gateway/reports/usage?days={days}&format=csv">Download CSV</a>
  <button onclick="downloadPDF()">Download PDF</button>
  <button onclick="window.print()">Print</button>
</div>

<!-- KPI Cards -->
<div class="kpi-grid">
  <div class="kpi">
    <div class="label">Total Sessions</div>
    <div class="value accent">{_format_number(s.total_sessions)}</div>
    <div class="sub">{_format_number(s.total_messages)} messages</div>
  </div>
  <div class="kpi">
    <div class="label">Chat Tokens Used</div>
    <div class="value green">{_format_number(s.total_session_tokens)}</div>
    <div class="sub">{_format_number(s.total_session_chars)} characters</div>
  </div>
  <div class="kpi">
    <div class="label">Chat Words</div>
    <div class="value cyan">{_format_number(s.total_session_words)}</div>
    <div class="sub">across all sessions</div>
  </div>
  <div class="kpi">
    <div class="label">Files Uploaded</div>
    <div class="value orange">{_format_number(s.total_files)}</div>
    <div class="sub">{_format_number(s.total_file_tokens)} filestore tokens</div>
  </div>
  <div class="kpi">
    <div class="label">File Characters</div>
    <div class="value accent">{_format_number(s.total_file_chars)}</div>
    <div class="sub">in markdown sent to Gemini</div>
  </div>
  <div class="kpi">
    <div class="label">Websites Scraped</div>
    <div class="value green">{_format_number(s.total_websites)}</div>
    <div class="sub">{_format_number(s.total_website_tokens)} filestore tokens</div>
  </div>
</div>

<!-- Charts -->
<div class="chart-grid">
  <div class="chart-card">
    <h3>Daily Message Volume</h3>
    <canvas id="dailyMsgChart"></canvas>
  </div>
  <div class="chart-card">
    <h3>Daily Token Consumption</h3>
    <canvas id="dailyTokenChart"></canvas>
  </div>
  <div class="chart-card">
    <h3>Messages by Role</h3>
    <canvas id="roleChart"></canvas>
  </div>
  <div class="chart-card">
    <h3>Avg Tokens per Message by Role</h3>
    <canvas id="avgTokenChart"></canvas>
  </div>
  <div class="chart-card">
    <h3>Top 10 Sessions by Token Usage</h3>
    <canvas id="topSessionsChart"></canvas>
  </div>
  <div class="chart-card">
    <h3>File Token Distribution (Top 15)</h3>
    <canvas id="fileTokenChart"></canvas>
  </div>
</div>

<!-- Sessions Table -->
<div class="section">
  <h2>Chat Sessions (Last {days} Days)</h2>
  <div style="overflow-x:auto;">
  <table>
    <thead><tr>
      <th>Session ID</th><th>Started</th><th>Messages</th>
      <th>Characters</th><th>Words</th><th>Tokens</th><th>Duration (min)</th><th>Status</th>
    </tr></thead>
    <tbody>{sessions_rows}</tbody>
  </table>
  </div>
</div>

<!-- Files Table -->
<div class="section">
  <h2>File Uploads</h2>
  <div style="overflow-x:auto;">
  <table>
    <thead><tr>
      <th>Filename</th><th>Ext</th><th>File Size</th>
      <th>FS Chars</th><th>FS Words</th><th>FS Tokens</th><th>Status</th><th>Date</th>
    </tr></thead>
    <tbody>{files_rows}</tbody>
  </table>
  </div>
</div>

<!-- Websites Table -->
<div class="section">
  <h2>Scraped Websites</h2>
  <div style="overflow-x:auto;">
  <table>
    <thead><tr>
      <th>URL</th><th>Title</th><th>Pages</th>
      <th>FS Chars</th><th>FS Words</th><th>FS Tokens</th><th>Status</th><th>Date</th>
    </tr></thead>
    <tbody>{websites_rows}</tbody>
  </table>
  </div>
</div>

</div><!-- /report-content -->

<script>
const chartDefaults = {{
  color: '#9ca3af',
  borderColor: '#2a2d3a',
  font: {{ family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}
}};
Chart.defaults.color = chartDefaults.color;
Chart.defaults.borderColor = chartDefaults.borderColor;

// Daily Message Volume
new Chart(document.getElementById('dailyMsgChart'), {{
  type: 'bar',
  data: {{
    labels: {daily_labels},
    datasets: [
      {{ label: 'User Messages', data: {daily_user_msgs}, backgroundColor: 'rgba(99,102,241,0.7)', borderRadius: 4 }},
      {{ label: 'Bot Responses', data: {daily_bot_msgs}, backgroundColor: 'rgba(34,197,94,0.7)', borderRadius: 4 }}
    ]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ position: 'top' }} }}, scales: {{ x: {{ stacked: false }}, y: {{ beginAtZero: true }} }} }}
}});

// Daily Token Consumption
new Chart(document.getElementById('dailyTokenChart'), {{
  type: 'line',
  data: {{
    labels: {daily_labels},
    datasets: [
      {{ label: 'Input Tokens (User)', data: {daily_user_tokens}, borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', fill: true, tension: 0.3 }},
      {{ label: 'Output Tokens (Bot)', data: {daily_bot_tokens}, borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', fill: true, tension: 0.3 }}
    ]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ position: 'top' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

// Messages by Role (Doughnut)
new Chart(document.getElementById('roleChart'), {{
  type: 'doughnut',
  data: {{
    labels: {role_labels},
    datasets: [{{ data: {role_counts}, backgroundColor: ['#6366f1', '#22c55e', '#f97316', '#06b6d4', '#ec4899'] }}]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ position: 'right' }} }} }}
}});

// Avg Tokens per Message by Role
new Chart(document.getElementById('avgTokenChart'), {{
  type: 'bar',
  data: {{
    labels: {role_labels},
    datasets: [{{ label: 'Avg Tokens', data: {role_avg_tokens}, backgroundColor: ['#8b5cf6', '#06b6d4', '#f97316', '#22c55e', '#ec4899'], borderRadius: 6 }}]
  }},
  options: {{ responsive: true, indexAxis: 'y', plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true }} }} }}
}});

// Top Sessions by Token Usage
new Chart(document.getElementById('topSessionsChart'), {{
  type: 'bar',
  data: {{
    labels: {top_labels},
    datasets: [
      {{ label: 'Tokens', data: {top_tokens}, backgroundColor: 'rgba(99,102,241,0.8)', borderRadius: 4 }},
      {{ label: 'Words', data: {top_words}, backgroundColor: 'rgba(6,182,212,0.6)', borderRadius: 4 }}
    ]
  }},
  options: {{ responsive: true, plugins: {{ legend: {{ position: 'top' }} }}, scales: {{ y: {{ beginAtZero: true }} }} }}
}});

// File Token Distribution
new Chart(document.getElementById('fileTokenChart'), {{
  type: 'bar',
  data: {{
    labels: {file_names},
    datasets: [{{ label: 'Filestore Tokens', data: {file_tokens}, backgroundColor: 'rgba(249,115,22,0.7)', borderRadius: 4 }}]
  }},
  options: {{ responsive: true, indexAxis: 'y', plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true }} }} }}
}});

function downloadPDF() {{
  const el = document.getElementById('report-content');
  const opt = {{
    margin: [10, 10, 10, 10],
    filename: 'usage-report-{days}d.pdf',
    image: {{ type: 'jpeg', quality: 0.98 }},
    html2canvas: {{ scale: 2, useCORS: true, backgroundColor: '#0f1117' }},
    jsPDF: {{ unit: 'mm', format: 'a3', orientation: 'landscape' }},
    pagebreak: {{ mode: ['avoid-all', 'css', 'legacy'] }}
  }};
  html2pdf().set(opt).from(el).save();
}}
</script>
</body>
</html>"""

    return HTMLResponse(content=html)


def _generate_csv(data: dict, days: int) -> StreamingResponse:
    """Generate CSV response from report data."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["=== CHAT SESSIONS ==="])
    writer.writerow(["Session ID", "Started At", "Messages", "Total Characters", "Total Words",
                      "Total Tokens", "Duration (min)", "Status", "Sentiment"])
    for row in data["sessions"]:
        writer.writerow([
            str(row.id), row.started_at, row.message_count,
            row.total_character_count, row.total_word_count, row.total_token_count,
            row.duration_minutes, row.archive_status, row.sentiment
        ])

    writer.writerow([])

    writer.writerow(["=== MESSAGE BREAKDOWN BY ROLE ==="])
    writer.writerow(["Role", "Message Count", "Total Characters", "Total Words", "Total Tokens",
                      "Avg Characters", "Avg Words", "Avg Tokens"])
    for row in data["msg_by_role"]:
        writer.writerow([
            row.role, row.msg_count, int(row.total_chars), int(row.total_words), int(row.total_tokens),
            round(float(row.avg_chars), 1), round(float(row.avg_words), 1), round(float(row.avg_tokens), 1)
        ])

    writer.writerow([])

    writer.writerow(["=== FILE UPLOADS ==="])
    writer.writerow(["Filename", "Extension", "File Size", "FS Characters", "FS Words",
                      "FS Tokens", "Status", "Docling", "Created"])
    for row in data["files"]:
        writer.writerow([
            row.original_filename, row.file_extension, row.file_size,
            row.filestore_character_count, row.filestore_word_count, row.filestore_token_count,
            row.processing_status, row.processed_by_docling, row.created_at
        ])

    writer.writerow([])

    writer.writerow(["=== SCRAPED WEBSITES ==="])
    writer.writerow(["URL", "Title", "Pages Scraped", "FS Characters", "FS Words",
                      "FS Tokens", "Status", "Depth", "Is Child", "Created"])
    for row in data["websites"]:
        writer.writerow([
            row.original_url, row.title, row.pages_scraped,
            row.filestore_character_count, row.filestore_word_count, row.filestore_token_count,
            row.processing_status, row.depth, "Yes" if row.parent_id else "No", row.created_at
        ])

    output.seek(0)
    filename = f"usage-report-{days}d-{datetime.utcnow().strftime('%Y%m%d')}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
