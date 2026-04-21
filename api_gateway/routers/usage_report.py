"""
Usage Report - Single Endpoint
GET /reports/usage → self-contained HTML report.
All filtering and Excel download handled client-side.
Protected by session auth middleware.
"""

import json
import html
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from sqlalchemy import text

logger = get_otel_logger("usage_report", "api-gateway")
router = APIRouter(prefix="/reports", tags=["reports"])


MEMORY_GB_SEC_RATE = 0.00000386
CPU_VCPU_SEC_RATE = 0.00000772
VOLUME_GB_SEC_RATE = 0.00000006
EGRESS_GB_RATE = 0.05
EMBEDDING_USD_PER_1M_TOKENS = 0.10
INPUT_CACHE_HIT_USD_PER_1M = 0.028
INPUT_CACHE_MISS_USD_PER_1M = 0.28
OUTPUT_USD_PER_1M = 0.42
MONTH_SECONDS = 30 * 24 * 60 * 60
GB_BYTES = 1024 * 1024 * 1024


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


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _in_current_month(row, *fields):
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for field in fields:
        dt = _parse_dt(row.get(field))
        if dt and dt >= month_start:
            return True
    return False


def _meta(row):
    value = row.get("request_metadata")
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _cache_tokens(row):
    meta = _meta(row)
    return int(meta.get("cache_read_tokens") or 0), int(meta.get("cache_write_tokens") or 0)


def _fmt_num(value, decimals=2):
    value = float(value or 0)
    if abs(value) >= 1000:
        return f"{value:,.{decimals}f}"
    return f"{value:.{decimals}f}"


def _fmt_money(value):
    return f"${float(value or 0):,.4f}"


def _fmt_tokens(value):
    value = float(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{int(value):,}"


def _build_excel_style_usage_report(data, tenant_id=""):
    tenants = data.get("tenants") or {}
    tenant_name = "All Tenants"
    if tenant_id and tenant_id in tenants:
        tenant = tenants[tenant_id]
        tenant_name = tenant.get("name") or tenant.get("slug") or tenant_id

    files = [
        row
        for row in data.get("files", [])
        if row.get("processing_status") in ("completed", "deleted")
        and _in_current_month(row, "completed_at", "created_at")
    ]
    websites = [
        row
        for row in data.get("websites", [])
        if row.get("processing_status") in ("completed", "deleted")
        and _in_current_month(row, "completed_at", "created_at")
    ]
    messages = [row for row in data.get("chat_messages", []) if _in_current_month(row, "created_at")]
    user_messages = [row for row in messages if row.get("role") == "user"]
    assistant_messages = [row for row in messages if row.get("role") == "assistant"]
    token_rows = [
        row
        for row in data.get("token_usage_log", [])
        if _in_current_month(row, "created_at")
    ]
    embedding_rows = [row for row in token_rows if row.get("api_call_type") == "embedding"]
    non_embedding_rows = [row for row in token_rows if row.get("api_call_type") != "embedding"]

    uploaded_bytes = sum(int(row.get("file_size") or 0) for row in files + websites)
    uploaded_gb = uploaded_bytes / GB_BYTES
    ingestion_tokens = sum(int(row.get("total_tokens") or row.get("prompt_tokens") or 0) for row in embedding_rows)
    ingestion_token_millions = ingestion_tokens / 1_000_000

    query_count = len(user_messages) or len(non_embedding_rows)
    prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in non_embedding_rows)
    completion_tokens = sum(int(row.get("completion_tokens") or 0) for row in non_embedding_rows)
    total_query_tokens = sum(int(row.get("total_tokens") or 0) for row in non_embedding_rows) or (prompt_tokens + completion_tokens)
    cache_read_tokens = 0
    cache_write_tokens = 0
    for row in non_embedding_rows:
        cache_read, cache_write = _cache_tokens(row)
        cache_read_tokens += cache_read
        cache_write_tokens += cache_write
    cache_hit_ratio = (cache_read_tokens / prompt_tokens) if prompt_tokens else 0
    cache_miss_tokens = max(prompt_tokens - cache_read_tokens, 0)
    avg_prompt_tokens = prompt_tokens / query_count if query_count else 0
    avg_completion_tokens = completion_tokens / query_count if query_count else 0
    response_bytes = sum(len((row.get("content") or "").encode("utf-8")) for row in assistant_messages)
    egress_gb = response_bytes / GB_BYTES

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    month_label = datetime.now(timezone.utc).strftime("%B %Y")
    uploaded_display_gb = max(uploaded_gb, 0)
    total_conversation_tokens = total_query_tokens or 2_500_000
    avg_tokens_per_conversation = (
        total_query_tokens / query_count if query_count else 1750
    )
    cache_hit_percent = cache_hit_ratio if prompt_tokens else 0.5
    rows = {idx: [""] * 13 for idx in range(1, 100)}

    def put(row_idx, col_idx, values):
        for offset, value in enumerate(values):
            rows[row_idx][col_idx - 1 + offset] = value

    put(1, 1, ["Ingestion assumption", "per month"])
    put(3, 1, ["Doc size or Egress", f"{uploaded_display_gb:.4f} GB"])
    put(4, 1, ["Avg tokens per GB", "~750k tokens (text)"])
    put(5, 1, ["Total tokens", _fmt_tokens(ingestion_tokens)])
    put(6, 1, ["Embedding model cost (Gemini File based search)", "$0.15 / 1M tokens (approx., for embeddings)", "Assuming 10 M tokens"])
    put(6, 11, ["DON'T MAKE ANY CHANGES IN VALUES IN ANY CELL BEFORE OUR CALL"])
    put(7, 1, ["volume price", "$0.0000006 per GB/sec"])
    put(8, 1, ["Volume", "5 GB"])
    put(9, 1, ["CPU ", 8])
    put(10, 1, ["Ingestion usage", "10 hours (36000 secs) in a month "])
    put(11, 6, ["Max memory/service - 8 GB RAM", "Max CPU/service - 8 (per replica)", "Max 5/ service"])
    put(11, 11, ["gemini-embedding-001"])
    put(12, 4, ["Serices"])
    put(12, 6, [0.00000386, 0.00000772, 0.00000006, 0.05, "", 0.15, 0.015])
    put(13, 6, ["Memory", "CPU", "Volumes", "Egress", "LLM Tokens", "Embedding API", "Object storage", "Cost USD"])
    put(14, 1, ["Query assumption", "Per month"])
    put(14, 4, ["Knowledgebase prod"])
    put(14, 6, ["", "", "", "", "10M", "", "", ""])
    put(15, 1, ["Conversations", f"appx {query_count or 4500}"])
    put(16, 1, ["CPU Load", "5 vCPU"])
    put(17, 1, ["RAM", "5 GB"])
    put(17, 6, ["Memory", "CPU", "Volumes", "Egress", "Tokens", "LLM API", "", "Cost USD"])
    put(18, 1, ["Volume", "5 GB"])
    put(18, 4, ["Query"])
    put(18, 10, [_fmt_tokens(total_query_tokens)])
    put(19, 1, ["Egress", f"{egress_gb:.4f} GB"])
    put(20, 1, ["Usage hours", "50 hours (180000 secs)"])
    put(20, 12, ["Total Cost /month", ""])
    put(21, 1, ["Tokens per conversation (avg)", f"{avg_prompt_tokens:.0f} in/ {avg_completion_tokens:.0f} out"])
    put(22, 1, ["Total tokens", f"assuming {_fmt_tokens(total_query_tokens)}"])
    put(23, 4, ["Deepseek"])
    put(24, 4, ["input cache-hit $0.028/M, input cache-miss $0.28/M, output $0.42/M"])
    put(25, 1, ["Component", "Description"])
    put(25, 4, ["same rates shown for chat vs reasoner"])
    put(26, 1, ["Compute (vCPU)", "Handles user queries, RAG orchestration, vector search API calls, document ingestion"])
    put(26, 4, ["Scenario", "Total tokens", "Cost USD", "", "Cache hit % (input)", "Reasoner % of queries"])
    put(27, 1, ["Memory (RAM)", "Holds in-memory embeddings, retrieved context, and caching"])
    put(27, 4, ["Low", total_conversation_tokens, "", "", f"{cache_hit_percent:.0%}", "20%"])
    put(28, 1, ["Volume Storage", "For app logs, caching embeddings, and configs, customer files persistently"])
    put(28, 4, ["Cache hit"])
    put(29, 1, ["Egress", "API responses + LLM API calls + DB calls + app responses (chat & KB)"])
    put(29, 4, ["Cache miss"])
    put(30, 4, ["Total"])
    put(33, 1, ["Total conversation tokens", total_conversation_tokens])
    put(34, 1, ["Tokens/conversation", round(avg_tokens_per_conversation, 2)])
    put(35, 1, ["Total conversations", ""])
    put(36, 1, ["Total system prompt tokens (assuming system prompt is 1000 words)", ""])
    put(85, 1, ["Credit calculation"])
    put(86, 1, ["User token per message", 50, "Verify"])
    put(87, 1, ["Response/chatbot tokens per message", 300, "Verify"])
    put(88, 1, ["Total tokens per message", ""])
    put(89, 1, ["Total messages per conversation", 5, "Verification possible after MVP launch"])
    put(90, 1, ["Total tokens per coversation", "", "Verify"])
    put(91, 1, ["Total tokens available in a month", total_conversation_tokens])
    put(92, 1, ["Total conversations in a month", ""])
    put(93, 1, ["Total credits per month ('total tokens' divided by 'total token per message')", ""])
    put(99, 8, [""])

    letters = "ABCDEFGHIJKLM"
    bold_cells = {
        "A1", "B1", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10",
        "A14", "B14", "A25", "B25", "M13", "M17", "M14", "M18",
        "L20", "M20", "A85", "A88", "B88", "A91", "B91", "A93", "B93",
    }

    def style_for(cell_id):
        col = letters.index(cell_id[0]) + 1
        row_idx = int(cell_id[1:])
        styles = []
        if row_idx in range(1, 11) and col in (1, 2):
            styles.append("peach")
        if row_idx in range(14, 23) and col in (1, 2):
            styles.append("green")
        if row_idx in range(12, 21) and col in range(4, 14):
            styles.append("blue")
        if row_idx in range(24, 31) and col in range(4, 10):
            styles.append("pink")
        if row_idx in range(25, 31) and col in (1, 2):
            styles.append("gray")
        if row_idx in range(33, 37) and col in (1, 2):
            styles.append("gray-dark")
        if row_idx in range(86, 94) and col in (1, 2):
            styles.append("peach")
        if cell_id == "K6":
            styles.append("warning")
        if cell_id in bold_cells:
            styles.append("bold")
        if col >= 6 or cell_id in {"B33", "B34", "B35", "B36", "B86", "B87", "B88", "B89", "B90", "B91", "B92", "B93"}:
            styles.append("num")
        return " ".join(styles)

    table_rows = []
    for row_idx in range(1, 100):
        cells = []
        for col_idx, value in enumerate(rows[row_idx], start=1):
            cell_id = f"{letters[col_idx - 1]}{row_idx}"
            classes = style_for(cell_id)
            cell_value = "" if value is None else str(value)
            cells.append(
                f'<td data-cell="{cell_id}" class="{classes}" contenteditable="true" spellcheck="false">{html.escape(cell_value)}</td>'
            )
        table_rows.append(f"<tr>{''.join(cells)}</tr>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Usage Report</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;background:#ffffff;color:#000000;margin:0;padding:24px}}
.wrap{{max-width:1680px;margin:0 auto;background:#ffffff;padding:0}}
h1{{font-size:22px;margin:0 0 4px}}
.meta{{font-size:13px;color:#6b7280;margin-bottom:18px}}
.sheet-shell{{position:relative;overflow:auto;border:1px solid #bfc7d7}}
.rate-banner{{position:absolute;left:48.5%;top:0;width:48%;height:86px;background:#11101c;color:#9b95a6;display:grid;grid-template-columns:repeat(4,1fr);align-items:center;text-align:center;font-weight:700;z-index:2}}
.rate-banner .icon{{color:#9b4ade;font-size:16px;margin-bottom:4px}}
.rate-banner .sub{{font-size:12px;color:#797486;margin-top:4px}}
table.sheet{{border-collapse:collapse;width:1800px;font-size:15px;table-layout:fixed}}
.sheet td{{border:1px solid #bfc7d7;background:#ffffff;padding:3px 5px;vertical-align:middle;height:23px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sheet td:nth-child(1){{width:245px}}
.sheet td:nth-child(2){{width:500px}}
.sheet td:nth-child(3){{width:80px}}
.sheet td:nth-child(4){{width:130px}}
.sheet td:nth-child(5),.sheet td:nth-child(6),.sheet td:nth-child(7),.sheet td:nth-child(8),.sheet td:nth-child(9),.sheet td:nth-child(10),.sheet td:nth-child(11),.sheet td:nth-child(12),.sheet td:nth-child(13){{width:132px}}
.sheet .peach{{background:#fae2d5}}
.sheet .green{{background:#d9f2d0}}
.sheet .blue{{background:#dbe9f7}}
.sheet .pink{{background:#f1ceee}}
.sheet .gray{{background:#e8e8e8}}
.sheet .gray-dark{{background:#d0d0d0}}
.sheet .warning{{background:#ff0000;color:#000000;font-weight:700}}
.sheet .bold{{font-weight:700}}
.sheet .num{{text-align:right;font-variant-numeric:tabular-nums}}
.sheet td[data-cell="D12"],.sheet td[data-cell="D14"],.sheet td[data-cell="D18"],.sheet td[data-cell="D23"],.sheet td[data-cell="D30"]{{font-weight:700}}
.sheet td[contenteditable="true"]{{cursor:text}}
.sheet td[contenteditable="true"]:hover{{outline:1px solid #a3a3a3;outline-offset:-1px}}
.sheet td[contenteditable="true"]:focus{{outline:2px solid #1a73e8;outline-offset:-2px;overflow:visible;text-overflow:clip;white-space:normal}}
.note{{margin-top:14px;font-size:12px;color:#6b7280;line-height:1.5}}
</style>
</head>
<body>
<div class="wrap">
<h1>Cost calculation for AI chatbot</h1>
<div class="meta">Tenant: {html.escape(tenant_name)} · Period: {html.escape(month_label)} month-to-date · Generated: {generated_at}</div>
<div class="sheet-shell">
<div class="rate-banner">
  <div><div class="icon">▣</div><div>Memory</div><div class="sub">$0.00000386 per GB / sec</div></div>
  <div><div class="icon">⚙</div><div>CPU</div><div class="sub">$0.00000772 per vCPU / sec</div></div>
  <div><div class="icon">▭</div><div>Volumes</div><div class="sub">$0.00000006 per GB / sec</div></div>
  <div><div class="icon">♟</div><div>Egress</div><div class="sub">$0.05 per GB</div></div>
</div>
<table class="sheet">
<tbody>
{''.join(table_rows)}
</tbody>
</table>
</div>
<div class="note">
Cells are editable in this browser view. Edits are local to the page and are not saved back to the database. Upload/ingestion size uses tenant-scoped <code>file_uploads.file_size</code> and <code>scraped_websites.file_size</code> for completed/deleted rows created or completed in this month. Those stored file_size counters are populated from <code>SUM(pg_column_size(document_chunks.content))</code> after chunk insertion.
</div>
</div>
<script>
const cell = id => document.querySelector(`[data-cell="${{id}}"]`);
const value = id => cell(id)?.textContent || "";
const num = id => {{
  const raw = value(id).replace(/,/g, "").replace(/\\$/g, "").trim();
  const match = raw.match(/-?\\d+(?:\\.\\d+)?/);
  if (!match) return 0;
  let n = Number(match[0]);
  if (/\\bM\\b/i.test(raw)) n *= 1000000;
  if (/\\bk\\b/i.test(raw)) n *= 1000;
  if (/%/.test(raw)) n /= 100;
  return Number.isFinite(n) ? n : 0;
}};
const money = n => Number(n || 0).toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 4 }});
const compact = n => Number(n || 0).toLocaleString(undefined, {{ maximumFractionDigits: 0 }});
const set = (id, text) => {{ const el = cell(id); if (el && document.activeElement !== el) el.textContent = text; }};
function recalc() {{
  set("F14", money(num("F12") * 36000 * 8));
  set("G14", money(num("G12") * 5 * 36000));
  set("H14", money(num("H12") * 0 * 2592000));
  set("I14", money(num("I12") * 0.5));
  set("K14", money(10 * num("K12")));
  set("L14", money(num("L12") * 0.1));
  set("M14", money(num("F14") + num("G14") + num("H14") + num("I14") + num("K14") + num("L14")));

  set("F18", money(num("F12") * 180000 * 2));
  set("G18", money(num("G12") * 180000 * 2));
  set("H18", money(num("H12") * 5 * 2592000));
  set("I18", money(20 * num("I12")));
  set("K18", money(num("E38")));
  set("M18", money(num("F18") + num("G18") + num("H18") + num("I18") + num("K18")));
  set("M20", money(num("M18") + num("M14")));

  set("E28", compact(num("H27") * num("E27")));
  set("F28", money(num("E28") * 0.28 / 1000000));
  set("E29", compact(num("H27") * num("E27")));
  set("F29", money(num("E29") * 0.42 / 1000000));
  set("F30", money(num("F28") + num("F29")));

  set("B35", compact(num("B33") / num("B34")));
  set("B36", compact(1000 * num("B35")));
  set("B88", compact(num("B87") + num("B86")));
  set("B90", compact(num("B89") * num("B88")));
  set("B92", compact(num("B91") / num("B90")));
  set("B93", compact(num("B91") / num("B88")));
  set("H99", money(180 / 20));
}}
document.querySelectorAll("[contenteditable=true]").forEach(el => el.addEventListener("input", recalc));
recalc();
</script>
</body>
</html>"""


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
                   pg_size_pretty(SUM(pg_column_size(content))) as content_pretty,
                   pg_size_pretty(SUM(pg_column_size(embedding))) as embedding_pretty
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
                   pg_size_pretty(SUM(pg_column_size(content))) as content_pretty,
                   pg_size_pretty(SUM(pg_column_size(embedding))) as embedding_pretty
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


@router.get("/usage", response_class=HTMLResponse)
async def usage_report(request: Request, tenant: str = ""):
    """Single endpoint. Filter by tenant on server-side via ?tenant= query param."""
    print(f"[USAGE REPORT] tenant param: '{tenant}'")
    data = await _fetch_all_data(tenant_id=tenant if tenant else None)
    print(
        f"[USAGE REPORT] returned {len(data.get('sessions', []))} sessions, {len(data.get('files', []))} files"
    )
    return HTMLResponse(
        content=_build_excel_style_usage_report(data, tenant_id=tenant if tenant else "")
    )
    data_json = json.dumps(data, default=str)

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
  <button onclick="setDays(30)" id="btn-30" class="active">30 Days</button>
  <button onclick="setDays(90)" id="btn-90">90 Days</button>
  <button onclick="setDays(180)" id="btn-180">180 Days</button>
  <button onclick="setDays(365)" id="btn-365">All Time</button>
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
  <thead><tr><th>Session ID</th><th>Started</th><th title="Total messages in this session">Msgs</th><th title="Provider-reported input tokens">Prompt Tokens</th><th title="Provider-reported output tokens">Completion Tokens</th><th title="Gemini count_tokens totals for captured context text only">Captured Context Tokens</th><th title="Gemini count_tokens totals for visible message text">Message Tokens</th><th>Status</th></tr></thead>
  <tbody id="sessions-table"></tbody>
</table></div></div>

<div class="section" id="token-log-section">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;border-bottom:1px solid var(--border);padding-bottom:8px">
    <h2 style="margin:0">Knowledge Ingestion</h2>
  </div>
  <div class="table-wrap"><table>
  <thead><tr><th>Date</th><th>Source</th><th>Chunk Row Count</th><th>Content KB</th><th>Embedding KB</th><th>Call Type</th><th>Model</th><th>Embedding Tokens</th><th>Chars</th><th>Words</th><th title="Size of text payload sent to embedding API (not S3 file size)">Size</th><th>Char/Token Ratio</th><th>Context</th></tr></thead>
  <tbody id="token-log-table"></tbody>
</table></div></div>
</div>

</div>

<script>
// === DATA ===
const RAW = """
        + data_json
        + """;
let currentDays = 30;
console.log('RAW keys:', RAW ? Object.keys(RAW) : 'empty');

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
  return (row.api_call_type || '') === 'embedding';
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
function metadataSummary(meta) {
  const parts = [];
  if(meta.batch_size) parts.push(`batch=${meta.batch_size}`);
  if(meta.dimensions) parts.push(`dims=${meta.dimensions}`);
  if(meta.image_size_bytes) parts.push(`image=${fmt(meta.image_size_bytes)} bytes`);
  if(meta.cache_ttl_seconds) parts.push(`ttl=${meta.cache_ttl_seconds}s`);
  if(meta.tool_call_count) parts.push(`tools=${meta.tool_call_count}`);
  if(meta.token_source) parts.push(`token_src=${meta.token_source}`);
  if(meta.webpage_name) parts.push(`page="${meta.webpage_name}"`);
  const url = meta.source_url || meta.url;
  if(url) parts.push(`url=${url}`);
  if(meta.website_id) parts.push(`site=${meta.website_id.substring(0,8)}`);
  
  if (parts.length === 0 && Object.keys(meta).length > 0) {
    return 'Keys: ' + Object.keys(meta).join(', ');
  }
  return parts.join(' · ') || '-';
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
  if(Array.isArray(chunks)) {
    if(chunks.length === 1 && (meta.batch_size || 0) > 1 && chunks[0] && chunks[0].includes('\\n---\\n')) {
      return chunks[0].split('\\n---\\n');
    }
    return chunks;
  }
  if(meta.input_text) return [meta.input_text];
  return [];
}
function nonIngestionUsageForSession(sessionId) {
  return (RAW.token_usage_log || [])
    .filter(r => r.session_id === sessionId && !isIngestionUsage(r))
    .sort((a,b) => (a.created_at||'').localeCompare(b.created_at||''));
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
  return `<div style="margin:8px 0 12px;border:1px solid var(--border);border-radius:6px;overflow:hidden;background:#fff">
    <div style="padding:8px 10px;background:rgba(22,163,74,.08);border-bottom:1px solid var(--border)">
      <div style="font-size:12px;font-weight:700;color:var(--green)">Provider Usage Ledger</div>
      <div style="font-size:11px;color:var(--muted);margin-top:3px">
        These rows are rooted in provider usage. Billable prompt is provider prompt minus provider cache read; completion is billable; cache read/write are cached; captured step rows below are non-billable diagnostics.
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
        <th>Date</th><th>Call</th><th>Provider</th><th>Model</th>
        <th style="text-align:right">Provider Prompt</th><th style="text-align:right">Billable Prompt</th><th style="text-align:right">Completion</th><th style="text-align:right">Total</th>
        <th style="text-align:right">Cache Read</th><th style="text-align:right">Cache Write</th><th>Billing</th><th>Source</th>
      </tr></thead>
      <tbody>
        ${rows.map(r => {
          const meta = parseMeta(r.request_metadata);
          const cache = getCacheTokens(meta);
          const billablePrompt = Math.max(0, (r.prompt_tokens || 0) - cache.read);
          return `<tr>
            <td>${fmtDateTime(r.created_at)}</td>
            <td>${callTypeLabel(r.api_call_type)}</td>
            <td>${r.provider || '-'}</td>
            <td>${r.model || '-'}</td>
            <td class="bd-num">${fmt(r.prompt_tokens)}</td>
            <td class="bd-num">${fmt(billablePrompt)}</td>
            <td class="bd-num">${fmt(r.completion_tokens)}</td>
            <td class="bd-num">${fmt(r.total_tokens)}</td>
            <td class="bd-num">${fmt(cache.read)}</td>
            <td class="bd-num">${fmt(cache.write)}</td>
            <td>${billingBadge('prompt billable','billable')} ${billingBadge('completion billable','billable')} ${cache.read || cache.write ? billingBadge('cache cached','cached') : ''}</td>
            <td><div class="metadata-snippet" title="${escHtml(JSON.stringify(meta))}">${escHtml(usageTokenSource(meta))}</div></td>
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
  const fileSizeBytes = files.reduce((a,r) => a+(r.file_size||0), 0);
  const totalWebsites = websites.length;
  const webTokens = websites.reduce((a,r) => a+(r.filestore_token_count||0), 0);
  const websiteSizeBytes = websites.reduce((a,r) => a+(r.file_size||0), 0);

  // Token log cache totals
  let totalCacheReadTokens = 0, totalCacheWriteTokens = 0;
  tokenLog.forEach(r => {
    const c = getCacheTokens(r.request_metadata);
    totalCacheReadTokens += c.read;
    totalCacheWriteTokens += c.write;
  });

  const ingestionTokens = ingestionTokenLog.reduce((a,r) => a + (r.total_tokens||0), 0);

  // === TOKEN SUMMARY ===
  document.getElementById('token-summary').innerHTML = `
    <h2>Token Usage Summary</h2>
    <div class="token-grid">
      <div class="token-item">
        <div class="token-label">Total Reported Tokens</div>
        <div class="token-value">${fmt(totalPromptTokens + totalCompletionTokens + ingestionTokens)}</div>
        <div class="token-detail">Chat sessions plus knowledge ingestion calls</div>
      </div>
      <div class="token-item">
        <div class="token-label">Provider Prompt Input</div>
        <div class="token-value" style="font-size:20px">${fmt(totalPromptTokens)}</div>
        <div class="token-detail">Prompt tokens returned by provider usage</div>
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
        <div class="token-label">Knowledge Ingestion</div>
        <div class="token-value" style="font-size:20px">${fmt(ingestionTokens)}</div>
        <div class="token-detail">${fmt(ingestionTokens)} tokens from embeddings</div>
      </div>
    </div>
  `;

  // === KPIs ===
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="label">Total Sessions</div><div class="value accent">${fmt(totalSessions)}</div><div class="sub">${fmt(totalMsgs)} messages total</div></div>
    <div class="kpi"><div class="label">Provider Prompt Tokens</div><div class="value green">${fmt(totalPromptTokens)}</div><div class="sub">Input tokens returned by provider usage</div></div>
    <div class="kpi"><div class="label">Output Tokens (Completion)</div><div class="value cyan">${fmt(totalCompletionTokens)}</div><div class="sub">Chat completion tokens</div></div>
    <div class="kpi"><div class="label">Cache Read Tokens</div><div class="value accent2">${fmt(totalCacheReadTokens)}</div><div class="sub">Reported cached input tokens</div></div>
    <div class="kpi"><div class="label">Cache Write Tokens</div><div class="value processing">${fmt(totalCacheWriteTokens)}</div><div class="sub">Reported cache creation tokens</div></div>
    <div class="kpi"><div class="label">Knowledge Ingestion Tokens</div><div class="value red">${fmt(ingestionTokens)}</div><div class="sub">Embeddings</div></div>
    <div class="kpi"><div class="label">Files Uploaded</div><div class="value orange">${fmt(totalFiles)}</div><div class="sub">${fmtBytes(fileSizeBytes)} total</div></div>
    <div class="kpi"><div class="label">WebPages Scraped</div><div class="value cyan">${fmt(totalWebsites)}</div><div class="sub">${fmtBytes(websiteSizeBytes)} total</div></div>
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
    sessionRow.innerHTML = `
      <td class="mono">${r.id}</td>
      <td>${fmtDateTime(r.started_at)}</td><td>${r.message_count||0}</td>
      <td class="token-cell">${fmt(r.total_prompt_token_count)}</td>
      <td class="token-cell">${fmt(r.total_completion_token_count)}</td>
      <td class="token-cell">${fmt((r.total_system_prompt_token_count||0)+(r.total_history_token_count||0)+(r.total_tool_def_token_count||0))}</td>
      <td class="token-cell">${fmt((r.total_user_msg_token_count||0)+(r.total_bot_response_token_count||0))}</td>
      <td>${badge(r.archive_status)}</td>`;
    sessionsEl.appendChild(sessionRow);
  });

  // === KNOWLEDGE INGESTION TABLE ===
  document.getElementById('token-log-table').innerHTML = ingestionTokenLog.slice(0,300).map(r => {
    const meta = parseMeta(r.request_metadata);
    const chunks = payloadTextChunks(meta);
    
    // Get source ID from metadata and look up chunk stats
    const sourceId = meta.website_id || meta.file_id || '';
    let chunkStats = { chunk_count: 0, total_content_bytes: 0, total_embedding_bytes: 0 };
    if (sourceId) {
      const stats = RAW.file_chunk_stats[sourceId] || RAW.website_chunk_stats[sourceId];
      if (stats) {
        chunkStats = {
          chunk_count: stats.chunk_count || 0,
          content_pretty: stats.content_pretty || '-',
          embedding_pretty: stats.embedding_pretty || '-'
        };
      }
    }
    
    const sourceName = meta.webpage_name || meta.source_url || meta.url || '-';
    
    return `<tr>
      <td>${fmtDateTime(r.created_at)}</td>
      <td class="mono source-cell">${trunc(sourceName, 40)}</td>
      <td>${chunkStats.chunk_count || '-'}</td>
      <td>${chunkStats.content_pretty || '-'}</td>
      <td>${chunkStats.embedding_pretty || '-'}</td>
      <td>${callTypeLabel(r.api_call_type)}</td>
      <td>${r.model||'-'}</td>
      <td class="token-cell">${fmt(r.total_tokens || r.prompt_tokens || 0)}</td>
      <td>${payloadChars(meta) ? fmt(payloadChars(meta)) : '-'}</td>
      <td>${payloadWords(meta) ? fmt(payloadWords(meta)) : '-'}</td>
      <td>${fmtBytes(payloadBytes(meta))}</td>
      <td>${(() => { const t=r.total_tokens||r.prompt_tokens||0,c=payloadChars(meta)||0; return t>0 ? (c/t).toFixed(2) : '-'; })()}</td>
      <td>${escHtml(metadataSummary(meta))}</td>
    </tr>
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
  const providerRow = document.createElement('tr');
  providerRow.className = 'msg-row';
  providerRow.innerHTML = `<td colspan="8" style="padding-left:24px">${renderSessionProviderUsage(sessionId)}</td>`;
  insertAfter.after(providerRow);
  insertAfter = providerRow;

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
          <th>Component</th><th style="text-align:right">Tokens</th><th style="text-align:right">Words</th><th style="text-align:right">Chars</th><th>What this means</th>
        </tr></thead>
        <tbody>
        ${m.role==='user' ? `
          <tr>
            <td class="bd-label">System Prompt</td>
            <td class="bd-num">${fmt(m.system_prompt_token_count)}</td>
            <td class="bd-num">${fmt(m.system_prompt_word_count)}</td>
            <td class="bd-num">${fmt(m.system_prompt_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.system_prompt_text)||'-'}</div><div style="font-size:10px;color:var(--muted);margin-top:3px">Gemini count_tokens diagnostic for the stored system prompt text.</div></td>
          </tr>
          <tr>
            <td class="bd-label">Conv. History</td>
            <td class="bd-num">${fmt(m.history_token_count)}</td>
            <td class="bd-num">${fmt(m.history_word_count)}</td>
            <td class="bd-num">${fmt(m.history_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.history_text)||'<i style="color:var(--muted)">No history (first message)</i>'}</div><div style="font-size:10px;color:var(--muted);margin-top:3px">Gemini count_tokens diagnostic for serialized conversation history.</div></td>
          </tr>
          <tr>
            <td class="bd-label">Tool Definitions</td>
            <td class="bd-num">${fmt(m.tool_def_token_count)}</td>
            <td class="bd-num">${fmt(m.tool_def_word_count)}</td>
            <td class="bd-num">${fmt(m.tool_def_char_count)}</td>
            <td class="bd-text" style="font-size:10px;color:var(--muted)">
              Gemini count_tokens diagnostic for the stored tool definition/schema text. Hidden provider request material is not inferred.
            </td>
          </tr>
          <tr>
            <td class="bd-label">User Message</td>
            <td class="bd-num">${fmt(m.user_msg_token_count)}</td>
            <td class="bd-num">${fmt(m.user_msg_word_count)}</td>
            <td class="bd-num">${fmt(m.user_msg_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.content)||'-'}</div><div style="font-size:10px;color:var(--muted);margin-top:3px">Gemini count_tokens diagnostic for only the user's visible message.</div></td>
          </tr>
          <tr style="background:rgba(79,70,229,.06);font-weight:600">
            <td class="bd-label">Provider Prompt Total</td>
            <td class="bd-num">${fmt(m.prompt_token_count)}</td>
            <td colspan="2" style="font-size:11px;color:var(--muted)">Gemini/Pydantic usage</td>
            <td style="font-size:10px;color:var(--muted)">Provider-reported prompt total for this turn. This is the billing number; rows above are diagnostics used to explain it.</td>
          </tr>
        ` : `
          <tr>
            <td class="bd-label">Bot Message Diagnostic</td>
            <td class="bd-num">${fmt(m.bot_response_token_count)}</td>
            <td class="bd-num">${fmt(m.bot_response_word_count)}</td>
            <td class="bd-num">${fmt(m.bot_response_char_count)}</td>
            <td class="bd-text"><div class="bd-text-preview" onclick="this.classList.toggle('expanded')">${escHtml(m.content)||'-'}</div><div style="font-size:10px;color:var(--muted);margin-top:3px">Gemini count_tokens diagnostic for the stored bot message text.</div></td>
          </tr>
          <tr style="background:rgba(79,70,229,.06);font-weight:600">
            <td class="bd-label">Provider Completion Total</td>
            <td class="bd-num">${fmt(m.completion_token_count)}</td>
            <td colspan="2" style="font-size:11px;color:var(--muted)">Gemini/Pydantic usage</td>
            <td style="font-size:10px;color:var(--muted)">Provider-reported output tokens for this turn. It may include tool-call generation and final text, so it can differ from the visible bot message diagnostic.</td>
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
  const ingestionTokenLog = tokenLog.filter(isIngestionUsage);

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

  // Sheet 4: Knowledge Ingestion
  const tokenLogData = ingestionTokenLog.map(r => {
    const meta = parseMeta(r.request_metadata);
    return {
      'Created': r.created_at||'',
      'Session ID': r.session_id||'',
      'Message ID': r.message_id||'',
      'Provider': r.provider||'',
      'Model': r.model||'',
      'Call Type': callTypeLabel(r.api_call_type),
      'Embedding Tokens': r.total_tokens || r.prompt_tokens || 0,
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
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tokenLogData), 'Knowledge Ingestion');

  // Sheet 5: Usage By Call Type
  const groupedUsageData = groupByCallType(ingestionTokenLog).map(g => ({
    'Call Type': callTypeLabel(g.call_type),
    'Raw Call Type': g.call_type,
    'Requests': g.requests,
    'Embedding Tokens': g.total || g.prompt,
    'Tool Calls': g.tools
  }));
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(groupedUsageData), 'Usage By Call Type');

  // Sheet 6: Largest Token Calls
  const topCallsData = [...ingestionTokenLog].sort((a,b) => (b.total_tokens||0) - (a.total_tokens||0)).slice(0,100).map(r => {
    const meta = parseMeta(r.request_metadata);
    return {
      'Created': r.created_at||'',
      'Call Type': callTypeLabel(r.api_call_type),
      'Provider': r.provider||'',
      'Model': r.model||'',
      'Embedding Tokens': r.total_tokens || r.prompt_tokens || 0,
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
currentTenant = getTenantFromUrl();
console.log('currentTenant from URL:', currentTenant);
initTenantFilter();
if (currentTenant) {
  document.getElementById('tenant-filter').value = currentTenant;
}
console.log('Sessions in RAW:', RAW.sessions ? RAW.sessions.length : 0);
render();
</script>
</body>
</html>"""
    )

    return HTMLResponse(content=html)
