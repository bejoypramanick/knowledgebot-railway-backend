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
    tenant_options = ['<option value="">All Tenants</option>']
    for tid, tenant in sorted(
        tenants.items(),
        key=lambda item: (item[1].get("name") or item[1].get("slug") or item[0]).lower(),
    ):
        label = tenant.get("name") or tenant.get("slug") or tid
        selected = " selected" if tid == tenant_id else ""
        tenant_options.append(
            f'<option value="{html.escape(tid)}"{selected}>{html.escape(label)}</option>'
        )

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
    rows = {idx: [""] * 16 for idx in range(1, 73)}

    def put(row_idx, col_idx, values):
        for offset, value in enumerate(values):
            rows[row_idx][col_idx - 1 + offset] = value

    put(6, 11, ["DON'T MAKE ANY CHANGES IN VALUES IN ANY CELL BEFORE OUR CALL"])
    put(8, 1, ["Monthly cost calculation"])
    put(9, 1, ["30 days ~ 2592000 secs"])
    put(9, 4, ["Max memory/service - 8 GB RAM"])
    put(9, 6, ["Max CPU/service - 8 (per replica)"])
    put(9, 8, ["Max 5GB / service"])
    put(10, 1, ["Services"])
    put(10, 3, ["Base price ->", 0.00000386, "Base price ->", 0.00000772, "Base price ->", 0.00000006, "Base price ->", 0.05, "Base price ->", 0.015, "Base price ->", 0.02])
    put(11, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM Tokens (M)", "OpenAI text-embedding-3-small", "Cost USD"])
    put(12, 1, ["Knowledgebase\nAssumptions:\n- 20 MB total raw embedding size limit\n- 5 hours (18000 secs) usage", "knowledge base", 2, "", 2, "", 0, "", 0.15, "", 0.05, "", "", "", ""])
    put(13, 2, ["kruzberg service", 3, "", 3, "", 0, "", 0, "", 0.05, "", 0, 0, ""])
    put(14, 2, ["celery file worker", 1, "", 2, "", 0, "", 0.6, "", 0, "", 0, 0, ""])
    put(15, 2, ["celery web worker", 1, "", 2, "", 0, "", 0.4, "", 0, "", 0, 0, ""])
    put(16, 14, ["Total->", ""])
    put(17, 1, ["Chatbot\nAssumptions:\n- 294 conversations\n- 5 mins per conversation\n- Total conv time-  sec", ""])
    put(17, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM tokens", "Gemini 2.5 Flash-Lite LLM API cost", "Cost USD"])
    put(18, 3, [3, "", 2, "", 0, "", 0.4, "", 0, "", "Check below in credit calculation table", "", ""])
    put(20, 1, ["API Gateway\nAssumptions:\nTotal time - knowledgebase + chatbot", ""])
    put(20, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM tokens"])
    put(21, 3, [1, "", 1, "", 0, "", 1, "", 0, "", 0, 0, ""])
    put(23, 1, ["Postgres+PGvector\nAssumptions:\nTotal time - knowledgebase + chatbot", ""])
    put(23, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM tokens"])
    put(24, 3, [1, "", 1, "", 1, "", 0.4, "", 0, "", 0, 0, ""])
    put(26, 1, ["Configuration\nAssumptions:\n- knowledge base time: 5 hours (18000 secs) usage"])
    put(26, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM tokens"])
    put(27, 3, [1, "", 1, "", 0, "", 0, "", 0, "", 0, 0, ""])
    put(29, 1, ["healthmonitor (turned OFF)"])
    put(29, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM tokens"])
    put(29, 15, ["health monitor is kept off"])
    put(30, 3, [0, "", 0, "", 0, "", 0, "", 0, "", 0, 0, ""])
    put(32, 1, ["Redis\nAssumptions:\n- 5 hours (18000 secs) usage"])
    put(32, 3, ["GBs of memory used", "Memory cost", "No. of vCPUs used", "CPU cost", "GBs of data stored", "Volumes cost", "GBs of data egressed", "Egress cost", "GBs of data stored", "Object storage cost", "LLM tokens"])
    put(33, 3, [1, "", 1, "", 0.5, "", 0, "", 0, "", 0, 0, ""])
    put(34, 14, ["Total->", ""])
    put(36, 1, ["1 conversation=", "5 turns (messages)"])
    put(37, 1, ["1 turn (message)=", "1 user input + 1 AI output"])
    put(38, 1, ["Average messages per conversation (assumption)", 5])
    put(39, 1, ["avg conversation time ", "5 mins"])
    put(41, 1, ["Credit calculation"])
    put(41, 10, ["Ingestion token calculation"])
    put(42, 1, ["INPUT TOKENS to Geminin per conversation"])
    put(42, 10, ["Tokens (M)", "Raw text bytes embedded (MB)", "Characters (M)", "Appx files", "Words (M)", "pg vector DB (MB)"])
    put(43, 1, ["System prompt tokens ", 2050])
    put(43, 10, [round(ingestion_token_millions or 7, 2), "", "", "", "", ""])
    put(44, 1, ["User token per conversation", "", "50 per user input"])
    put(45, 1, ["1st: sys prompt + tool call", ""])
    put(45, 13, ["USD", "INR"])
    put(46, 1, ["2nd to 5th message: tool call", ""])
    put(46, 12, ["Subcription price per customer", 25, ""])
    put(47, 1, ["coversation history per conversation (2nd to 5th message)", "", "- 50 user input\n- 300 response"])
    put(47, 12, ["Cost per customer", "", ""])
    put(48, 1, ["total input tokens for conversation", ""])
    put(48, 5, ["Gemini 2.5 flash-lite"])
    put(48, 12, ["Profit per customer", "", ""])
    put(49, 1, ["Average input tokens per turn", ""])
    put(49, 6, ["Base price / M tokens", "Cost (USD)"])
    put(49, 12, ["Total customers", 10, ""])
    put(50, 1, ["OUTPUT TOKENs from Gemini per conversation"])
    put(50, 5, ["Input tokens (user chat queries)", 0.1, ""])
    put(50, 12, ["Total profit", "", ""])
    put(51, 1, ["Tool call output token per input message", 60, "- 50 user input\n- tool definitions only for 1st call"])
    put(51, 5, ["Output (Chatbot responses)", 0.4, ""])
    put(51, 12, ["USD-INR convertion rate", 93.12345])
    put(52, 1, ["Response/chatbot tokens per turn (assumption)", 300])
    put(52, 5, ["Context cache tokens for system prompt", 0.01, ""])
    put(53, 1, ["Total output token for conversation", ""])
    put(53, 6, ["Total conv token cost", ""])
    put(54, 1, ["Total messages per conversation", 5])
    put(55, 1, ["Total conversation tokens in a month", total_conversation_tokens or 6000000])
    put(55, 5, ["Context cache storage price per hour", 1])
    put(56, 1, ["Average input+output tokens in 1 coversation", ""])
    put(56, 5, ["Total conversation time in hours", ""])
    put(57, 1, ["Total conversations in a month", ""])
    put(57, 6, ["Total storage cost per month", ""])
    put(58, 1, ["Input tokens used in a month", ""])
    put(58, 6, ["Grand total", ""])
    put(59, 1, ["Output tokens used in a month", ""])
    put(60, 1, ["Total output AI messages in a month", ""])
    put(61, 1, ["Appx time per conversation", "", "secs (5mins)"])
    put(62, 1, ["Total time for all conversations in a month", "", "", "hours per month"])
    put(63, 1, ["Average input+output tokens in 1 turn (message)", ""])
    put(64, 1, ["System prompt tokens for caching usage"])
    put(65, 1, ["System prompt tokens ", ""])
    put(66, 1, ["Total turns (messages) where cached system prompt is referred", ""])
    put(67, 1, ["Total cached system prompt token usage in a month", ""])
    put(70, 1, ["Credit system"])
    put(71, 1, ["1 credit", 10000, "conversation tokens"])
    put(72, 1, ["Total credits available in a month", ""])

    derivations = {
        10: "How this table is derived",
        12: "Knowledgebase cost = memory cost + CPU cost + volume storage cost + egress cost + embedding API cost + object storage cost. Memory cost = memory GB used x memory price x 18,000 seconds. CPU cost = vCPUs used x CPU price x 18,000 seconds.",
        13: "Kreuzberg service cost uses the same service formula: memory GB x memory price x 18,000 seconds + vCPUs x CPU price x 18,000 seconds + storage/egress/object storage costs.",
        14: "Celery file worker cost = memory cost + CPU cost + volume cost + egress cost + object storage cost. Egress comes from file-processing traffic assumption.",
        15: "Celery web worker cost = memory cost + CPU cost + volume cost + egress cost + object storage cost. Egress comes from website-scraping traffic assumption.",
        16: "Knowledgebase total = sum of all knowledgebase service rows above.",
        17: "Chatbot runtime uses total conversation time from the credit calculation table below.",
        18: "Chatbot cost = memory GB x memory price x total conversation seconds + vCPUs x CPU price x total conversation seconds + storage + egress + LLM API cost. LLM API cost comes from the credit calculation table.",
        20: "API Gateway runtime = chatbot conversation seconds + 18,000 knowledgebase seconds.",
        21: "API Gateway cost = memory + CPU + volume storage + egress + object storage, using API Gateway runtime seconds.",
        23: "Postgres/PGVector runtime = chatbot conversation seconds + 18,000 knowledgebase seconds.",
        24: "Postgres/PGVector cost = memory + CPU + volume storage + egress + object storage, using Postgres/PGVector runtime seconds.",
        27: "Configuration service cost = memory + CPU + storage + egress + object storage, using 18,000 knowledgebase seconds.",
        30: "Health monitor cost would be memory + storage + other costs, but the service is marked off so CPU/egress/object storage inputs stay zero.",
        33: "Redis cost = memory + CPU + volume storage + egress + object storage, using 18,000 seconds and Redis storage assumptions.",
        34: "Monthly infrastructure total = knowledgebase total + chatbot total + API Gateway total + Postgres/PGVector total + configuration total + health monitor total + Redis total.",
        36: "Conversation model: one conversation has five turns/messages.",
        37: "One turn means one user input plus one AI output.",
        38: "Average messages per conversation is an editable assumption used by downstream token math.",
        39: "Average conversation time is an editable assumption; workbook uses five minutes per conversation.",
        43: "Ingestion size estimates: raw text MB = token millions x 2.8; characters in millions = token millions x 2.8; approximate files = token millions x 170; words in millions = token millions x 0.4; pgvector DB MB = raw text MB x 6.",
        44: "User tokens per conversation = user tokens per message x five user messages.",
        45: "First message input tokens = system prompt tokens + first tool-call tokens.",
        46: "Follow-up tool-call tokens = tool-call tokens per follow-up message x four follow-up messages. Subscription price in INR = subscription price in USD x USD-INR rate.",
        47: "Conversation history tokens add each prior user/AI pair as context for later turns. Cost per customer = monthly infrastructure total. INR cost = USD cost x USD-INR rate.",
        48: "Total input tokens per conversation = user tokens + first-message tokens + follow-up tool-call tokens + conversation-history tokens. Profit per customer = subscription price - cost per customer.",
        49: "Average input tokens per turn = total input tokens per conversation divided by five turns. Total customers is an editable assumption.",
        50: "Monthly input-token cost = input-token price per million x monthly input tokens / 1,000,000. Total profit = total customers x profit per customer.",
        51: "Monthly output-token cost = output-token price per million x monthly output tokens / 1,000,000. USD-INR rate converts USD values to INR.",
        52: "Context-cache cost = cache-token price per million x cached system-prompt token usage / 1,000,000.",
        53: "Output tokens per conversation = response tokens per turn plus tool-call output tokens, multiplied by five turns. Total conversation token cost = input cost + output cost + cache cost.",
        54: "Total messages per conversation is the editable message-count assumption.",
        55: "Total conversation tokens in a month is the selected monthly token budget for this scenario.",
        56: "Average total tokens per conversation = total output tokens per conversation + total input tokens per conversation. Total conversation hours comes from total conversation seconds divided by 3,600.",
        57: "Total conversations per month = monthly token budget divided by average tokens per conversation. Storage cost = conversation hours x cache storage price x system prompt tokens / 1,000,000.",
        58: "Monthly input tokens = conversations per month x input tokens per conversation. Grand LLM total = storage cost + conversation token cost.",
        59: "Monthly output tokens = conversations per month x output tokens per conversation.",
        60: "Total output AI messages = conversations per month x five AI outputs per conversation.",
        61: "Approx time per conversation = five minutes x sixty seconds.",
        62: "Total conversation seconds = seconds per conversation x conversations per month. Hours = total seconds / 3,600.",
        63: "Average tokens per turn = average input tokens per turn + response tokens per turn + tool-call output tokens per turn.",
        65: "System prompt tokens for caching reuse the system prompt token assumption above.",
        66: "Cached system-prompt references = conversations per month x four cached turns after the first turn.",
        67: "Cached system-prompt token usage = cached references x system prompt tokens.",
        70: "Credit system converts monthly token budget into credits.",
        71: "One credit equals 10,000 conversation tokens.",
        72: "Total credits available = monthly token budget divided by tokens per credit.",
    }
    put(10, 16, ["Simple formula / how this is derived"])
    for row_idx, formula in derivations.items():
        put(row_idx, 16, [formula])

    letters = "ABCDEFGHIJKLMNOP"
    service_dropdown_cells = {
        "C12", "C13", "C14", "C15", "E12", "E13", "E14", "E15",
        "C18", "E18", "C21", "E21", "C24", "E24", "C27", "E27",
        "C33", "E33",
    }
    dropdowns = {
        cell_id: [str(value) for value in range(1, 9)]
        for cell_id in service_dropdown_cells
    }
    dropdowns["B55"] = [
        "1000000", "2000000", "3000000", "8000000", "5000000", "6000000",
        "7000000", "10000000", "12000000", "13000000", "11000000",
        "500000", "300000", "5500000",
    ]
    formula_tooltips = {
        "D12": "Memory cost = $D$10 * 18000 * C12",
        "F12": "CPU cost = $F$10 * E12 * 18000",
        "H12": "Volumes cost = $H$10 * G12 * 2592000",
        "J12": "Egress cost = $J$10 * I12",
        "L12": "Object storage cost = $L$10 * K12",
        "M12": "LLM Tokens (M) = J43 from ingestion token calculation",
        "N12": "Embedding cost = M12 * N10",
        "O12": "Cost USD = D12 + F12 + H12 + J12 + N12 + L12",
        "O16": "Knowledgebase total = SUM(O11:O15)",
        "B17": "Chatbot total conversation time = B62",
        "D18": "Memory cost = $D$10 * B62 * C18",
        "F18": "CPU cost = $F$10 * E18 * B62",
        "H18": "Volumes cost = $H$10 * G18 * 2592000",
        "J18": "Egress cost = $J$10 * I18",
        "L18": "Object storage cost = $L$10 * K18",
        "N18": "LLM API cost = G58 from credit calculation",
        "O18": "Cost USD = D18 + F18 + H18 + J18 + N18 + L18",
        "B20": "API Gateway total time = B62 + 18000",
        "B23": "Postgres+PGvector total time = B62 + 18000",
        "O34": "Grand infrastructure total = SUM(O16,O18,O21,O24,O27,O30,O33)",
        "K43": "Raw text bytes embedded (MB) = 2.8 * J43",
        "L43": "Characters (M) = J43 * 2.8",
        "M43": "Approx files = 170 * J43",
        "N43": "Words (M) = J43 * 0.4",
        "O43": "pg vector DB (MB) = K43 * 6",
        "B44": "User token per conversation = 50 * 5",
        "B45": "1st message input = B43 + 1500",
        "B46": "2nd to 5th message tool call = 1500 * 4",
        "B47": "Conversation history = (300+50)+2*(300+50)+3*(300+50)+4*(300+50)",
        "B48": "Total input tokens = SUM(B44:B47)",
        "B49": "Average input tokens per turn = B48 / 5",
        "G50": "Input token cost = F50 * B58 / 1000000",
        "G51": "Output token cost = F51 * B59 / 1000000",
        "G52": "Context cache token cost = F52 * B67 / 1000000",
        "B53": "Total output token per conversation = (B52 + B51) * 5",
        "G53": "Total conversation token cost = SUM(G50:G52)",
        "B56": "Average input+output tokens in one conversation = B53 + B48",
        "B57": "Total conversations in a month = B55 / B56",
        "B58": "Input tokens used in a month = B57 * B48",
        "B59": "Output tokens used in a month = B57 * B53",
        "B60": "Total output AI messages in a month = B57 * 5",
        "B61": "Approx time per conversation = 5 * 60 seconds",
        "B62": "Total time for all conversations = B61 * B57",
        "C62": "Total conversation time in hours = B62 / (60 * 60)",
        "B63": "Average input+output tokens in one turn = B49 + B52 + B51",
        "B65": "System prompt tokens for caching = B43",
        "B66": "Cached turns in month = B57 * 4",
        "B67": "Cached system prompt token usage = B66 * B65",
        "F56": "Total conversation time in hours = C62",
        "G57": "Storage cost per month = F56 * F55 * B65 / 1000000",
        "G58": "Grand total LLM cost = SUM(G57,G53)",
        "M47": "Cost per customer = O34",
        "N46": "Subscription price INR = M46 * M51",
        "N47": "Cost per customer INR = M47 * M51",
        "M48": "Profit per customer = M46 - M47",
        "N48": "Profit per customer INR = M48 * M51",
        "M50": "Total profit = M49 * M48",
        "N50": "Total profit INR = M50 * M51",
        "B72": "Total credits available in a month = B55 / B71",
    }
    for row_idx in [13, 14, 15, 21, 24, 27, 30, 33]:
        formula_tooltips.update(
            {
                f"D{row_idx}": "Memory cost = base memory price * seconds used * GB memory",
                f"F{row_idx}": "CPU cost = base CPU price * vCPU count * seconds used",
                f"H{row_idx}": "Volumes cost = base volume price * stored GB * 2592000 seconds",
                f"J{row_idx}": "Egress cost = base egress price * egress GB",
                f"L{row_idx}": "Object storage cost = base object storage price * stored GB",
                f"O{row_idx}": "Cost USD = memory + CPU + volume + egress + LLM/API + object storage",
            }
        )

    def tooltip_for(cell_id, cell_value):
        if cell_id in formula_tooltips:
            return formula_tooltips[cell_id]
        if cell_id in dropdowns:
            return f"Excel dropdown input. Allowed values: {', '.join(dropdowns[cell_id])}."
        row_idx = int(cell_id[1:])
        col = letters.index(cell_id[0]) + 1
        if row_idx in range(10, 35) and col in (3, 5, 7, 9, 11, 13):
            return "Editable service usage input from the detailed calculation sheet."
        if row_idx in range(10, 35) and col in (4, 6, 8, 10, 12, 14, 15):
            return "Calculated cost field derived from the service input cells and base prices."
        if row_idx in range(41, 73):
            return "Credit and token calculation field from the detailed calculation sheet."
        if cell_value:
            return f"Workbook field: {cell_value}"
        return f"Editable blank cell {cell_id} from the detailed calculation sheet."

    bold_cells = {
        "A1", "B1", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10",
        "A14", "B14", "A25", "B25", "M13", "M17", "M14", "M18",
        "L20", "M20", "A85", "A88", "B88", "A91", "B91", "A93", "B93",
    }

    def style_for(cell_id):
        col = letters.index(cell_id[0]) + 1
        row_idx = int(cell_id[1:])
        styles = []
        if col == 16:
            styles.append("formula-col")
        if row_idx in range(10, 35):
            palette = {1: "svc", 2: "svc", 3: "mem", 4: "mem", 5: "cpu", 6: "cpu", 7: "vol", 8: "vol", 9: "egress", 10: "egress", 11: "obj", 12: "obj", 13: "svc", 14: "svc", 15: "svc", 16: "formula-col"}
            if col in palette:
                styles.append(palette[col])
        if cell_id in {"O16", "O18", "O21", "O24", "O27", "O30", "O33"}:
            styles.append("yellow")
        if cell_id in {"N34", "O34"}:
            styles.append("cyan")
        if row_idx in range(36, 40) and col in (1, 2):
            styles.append("soft-yellow")
        if row_idx == 41 and col == 1:
            styles.append("orange")
        if row_idx == 41 and col == 10:
            styles.append("tan")
        if row_idx in (42, 64, 65, 66, 67) and col in (1, 2):
            styles.append("pale-blue")
        if row_idx in range(43, 50) and col in (1, 2):
            styles.append("blue2")
        if row_idx in (42, 43) and col in range(10, 16):
            styles.append("gray")
        if row_idx in range(46, 52) and col in range(12, 15):
            styles.append("pink2")
        if row_idx in range(54, 64) and col in (1, 2):
            styles.append("peach")
        if row_idx in range(60, 63) and col in (1, 2):
            styles.append("green2")
        if row_idx in range(48, 59) and col in range(5, 8):
            styles.append("soft-yellow")
        if cell_id == "K6":
            styles.append("warning")
        if cell_id in bold_cells:
            styles.append("bold")
        if col >= 6 or cell_id in {"B33", "B34", "B35", "B36", "B86", "B87", "B88", "B89", "B90", "B91", "B92", "B93"}:
            styles.append("num")
        return " ".join(styles)

    display_col_indexes = [16] + list(range(1, 16))

    def render_rows(start_row, end_row):
        rendered_rows = []
        for row_idx in range(start_row, end_row + 1):
            cells = []
            for col_idx in display_col_indexes:
                value = rows[row_idx][col_idx - 1]
                cell_id = f"{letters[col_idx - 1]}{row_idx}"
                classes = style_for(cell_id)
                cell_value = "" if value is None else str(value)
                tooltip = html.escape(tooltip_for(cell_id, cell_value))
                if cell_id in dropdowns:
                    select_options = []
                    selected_value = cell_value.replace(",", "")
                    for option in dropdowns[cell_id]:
                        selected = " selected" if option == selected_value else ""
                        select_options.append(
                            f'<option value="{html.escape(option)}"{selected}>{html.escape(option)}</option>'
                        )
                    cell_html = (
                        f'<select data-dropdown-cell="{cell_id}" aria-label="{cell_id}">'
                        f'{"".join(select_options)}</select>'
                    )
                    cells.append(f'<td data-cell="{cell_id}" class="{classes} dropdown-cell" title="{tooltip}">{cell_html}</td>')
                else:
                    cells.append(
                        f'<td data-cell="{cell_id}" class="{classes}" title="{tooltip}" contenteditable="true" spellcheck="false">{html.escape(cell_value)}</td>'
                    )
            rendered_rows.append(f"<tr>{''.join(cells)}</tr>")
        return "".join(rendered_rows)

    sections = [
        ("Base Rates", 6, 11),
        ("Knowledgebase", 12, 16),
        ("Chatbot", 17, 18),
        ("API Gateway", 20, 21),
        ("Postgres + PGVector", 23, 24),
        ("Configuration", 26, 27),
        ("Health Monitor", 29, 30),
        ("Redis", 32, 34),
        ("Conversation Assumptions", 36, 39),
        ("Credit Calculation", 41, 63),
        ("System Prompt Cache", 64, 67),
        ("Credit System", 70, 72),
    ]
    table_sections = []
    for title, start_row, end_row in sections:
        table_sections.append(
            f"""
<section class="report-section">
  <div class="section-title">{html.escape(title)}</div>
  <div class="section-scroll">
    <table class="sheet">
      <tbody>
        {render_rows(start_row, end_row)}
      </tbody>
    </table>
  </div>
</section>"""
        )

    table_rows = []
    for row_idx in range(6, 73):
        cells = []
        for col_idx, value in enumerate(rows[row_idx], start=1):
            cell_id = f"{letters[col_idx - 1]}{row_idx}"
            classes = style_for(cell_id)
            cell_value = "" if value is None else str(value)
            tooltip = html.escape(tooltip_for(cell_id, cell_value))
            if cell_id in dropdowns:
                select_options = []
                selected_value = cell_value.replace(",", "")
                for option in dropdowns[cell_id]:
                    selected = " selected" if option == selected_value else ""
                    select_options.append(
                        f'<option value="{html.escape(option)}"{selected}>{html.escape(option)}</option>'
                    )
                cell_html = (
                    f'<select data-dropdown-cell="{cell_id}" aria-label="{cell_id}">'
                    f'{"".join(select_options)}</select>'
                )
                cells.append(f'<td data-cell="{cell_id}" class="{classes} dropdown-cell" title="{tooltip}">{cell_html}</td>')
            else:
                cells.append(
                    f'<td data-cell="{cell_id}" class="{classes}" title="{tooltip}" contenteditable="true" spellcheck="false">{html.escape(cell_value)}</td>'
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
.topbar{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:10px}}
h1{{font-size:22px;margin:0 0 4px}}
.meta{{font-size:13px;color:#6b7280;margin-bottom:18px}}
.tenant-picker{{margin-left:auto;text-align:right;font-size:12px;color:#4b5563}}
.tenant-picker label{{display:block;font-weight:700;margin-bottom:4px}}
.tenant-picker select{{min-width:240px;border:1px solid #9ca3af;border-radius:6px;background:#fff;padding:7px 9px;font-size:13px}}
.sections{{display:flex;flex-direction:column;gap:18px}}
.report-section{{border:1px solid #bfc7d7;background:#ffffff}}
.section-title{{position:sticky;left:0;background:#111827;color:#ffffff;font-weight:700;padding:8px 10px;font-size:13px;letter-spacing:.01em}}
.section-scroll{{overflow:auto;max-width:100%}}
table.sheet{{border-collapse:collapse;width:2500px;font-size:13px;table-layout:fixed}}
.sheet td{{border:1px solid #bfc7d7;background:#ffffff;padding:3px 5px;vertical-align:middle;height:23px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.sheet td:nth-child(1){{width:430px}}
.sheet td:nth-child(2){{width:256px}}
.sheet td:nth-child(3){{width:161px}}
.sheet td:nth-child(4),.sheet td:nth-child(6){{width:143px}}
.sheet td:nth-child(5),.sheet td:nth-child(7),.sheet td:nth-child(9){{width:119px}}
.sheet td:nth-child(8),.sheet td:nth-child(10){{width:132px}}
.sheet td:nth-child(11),.sheet td:nth-child(12),.sheet td:nth-child(13),.sheet td:nth-child(16){{width:130px}}
.sheet td:nth-child(14){{width:190px}}
.sheet td:nth-child(15){{width:226px}}
.sheet .svc{{background:#a4c2f4}}
.sheet .mem,.sheet .obj{{background:#d9ead3}}
.sheet .cpu{{background:#d9d2e9}}
.sheet .vol{{background:#fff2cc}}
.sheet .egress{{background:#f9cb9c}}
.sheet .peach{{background:#fae2d5}}
.sheet .yellow{{background:#ffff00}}
.sheet .cyan{{background:#00ffff}}
.sheet .soft-yellow{{background:#ffe599}}
.sheet .orange{{background:#ff9900}}
.sheet .tan{{background:#f6b26b}}
.sheet .pale-blue{{background:#cfe2f3}}
.sheet .blue2{{background:#c9daf8}}
.sheet .gray{{background:#cccccc}}
.sheet .pink2{{background:#f4cccc}}
.sheet .green2{{background:#b6d7a8}}
.sheet .formula-col{{background:#eef2ff;color:#1f2937;font-family:"SFMono-Regular",Consolas,monospace;font-size:12px;text-align:left;white-space:normal}}
.sheet td.formula-col{{position:sticky;left:0;z-index:1;border-right:2px solid #94a3b8}}
.sheet .warning{{background:#ff0000;color:#000000;font-weight:700}}
.sheet .bold{{font-weight:700}}
.sheet .num{{text-align:right;font-variant-numeric:tabular-nums}}
.sheet td[data-cell="A8"],.sheet td[data-cell="A41"],.sheet td[data-cell="J41"],.sheet td[data-cell="A70"]{{font-weight:700}}
.sheet td[data-cell^="A"]{{white-space:pre-line}}
.sheet td[data-cell^="B"],.sheet td[data-cell^="C"]{{white-space:pre-line}}
.sheet td[contenteditable="true"]{{cursor:text}}
.sheet td[contenteditable="true"]:hover{{outline:1px solid #a3a3a3;outline-offset:-1px}}
.sheet td[contenteditable="true"]:focus{{outline:2px solid #1a73e8;outline-offset:-2px;overflow:visible;text-overflow:clip;white-space:normal}}
.sheet select{{width:100%;height:100%;border:0;background:transparent;font:inherit;color:inherit;text-align:inherit;outline:0}}
.sheet .dropdown-cell{{padding:0 4px}}
.note{{margin-top:14px;font-size:12px;color:#6b7280;line-height:1.5}}
</style>
</head>
<body>
<div class="wrap">
<div class="topbar">
  <div>
    <h1>Cost calculation for AI chatbot</h1>
    <div class="meta">Tenant: {html.escape(tenant_name)} · Period: {html.escape(month_label)} month-to-date · Generated: {generated_at}</div>
  </div>
  <form class="tenant-picker" method="get" action="">
    <label for="tenant-select">Tenant</label>
    <select id="tenant-select" name="tenant" onchange="this.form.submit()">
      {''.join(tenant_options)}
    </select>
  </form>
</div>
<div class="sections">
{''.join(table_sections)}
</div>
<div class="note">
Cells are editable in this browser view. Edits are local to the page and are not saved back to the database. Upload/ingestion size uses tenant-scoped <code>file_uploads.file_size</code> and <code>scraped_websites.file_size</code> for completed/deleted rows created or completed in this month. Those stored file_size counters are populated from <code>SUM(pg_column_size(document_chunks.content))</code> after chunk insertion.
</div>
</div>
<script>
const cell = id => document.querySelector(`[data-cell="${{id}}"]`);
const value = id => {{
  const el = cell(id);
  if (!el) return "";
  const select = el.querySelector("select");
  return select ? select.value : el.textContent;
}};
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
const safe = n => Number.isFinite(Number(n)) ? Number(n) : 0;
const money = n => safe(n).toLocaleString(undefined, {{ minimumFractionDigits: 2, maximumFractionDigits: 4 }});
const compact = n => safe(n).toLocaleString(undefined, {{ maximumFractionDigits: 0 }});
const set = (id, text) => {{ const el = cell(id); if (el && document.activeElement !== el) el.textContent = text; }};
const fixed = (n, d = 4) => safe(n).toLocaleString(undefined, {{ minimumFractionDigits: d, maximumFractionDigits: d }});
function recalc() {{
  const monthlySeconds = 2592000;
  for (const r of [12,13,14,15]) {{
    set(`D${{r}}`, fixed(num("D10") * 18000 * num(`C${{r}}`)));
    set(`F${{r}}`, fixed(num("F10") * num(`E${{r}}`) * 18000));
    set(`H${{r}}`, fixed(num("H10") * num(`G${{r}}`) * monthlySeconds));
    set(`J${{r}}`, fixed(num("J10") * num(`I${{r}}`)));
    set(`L${{r}}`, fixed(num("L10") * num(`K${{r}}`)));
    if (r !== 12) set(`O${{r}}`, fixed(num(`D${{r}}`) + num(`F${{r}}`) + num(`H${{r}}`) + num(`J${{r}}`) + num(`N${{r}}`) + num(`L${{r}}`)));
  }}
  set("M12", fixed(num("J43"), 2));
  set("N12", fixed(num("M12") * num("N10")));
  set("O12", fixed(num("D12") + num("F12") + num("H12") + num("J12") + num("N12") + num("L12")));
  set("O16", fixed(num("O11") + num("O12") + num("O13") + num("O14") + num("O15")));

  set("B17", fixed(num("B62"), 2));
  set("D18", fixed(num("D10") * num("B62") * num("C18")));
  set("F18", fixed(num("F10") * num("E18") * num("B62")));
  set("H18", fixed(num("H10") * num("G18") * monthlySeconds));
  set("J18", fixed(num("J10") * num("I18")));
  set("L18", fixed(num("L10") * num("K18")));
  set("N18", fixed(num("G58")));
  set("O18", fixed(num("D18") + num("F18") + num("H18") + num("J18") + num("N18") + num("L18")));

  for (const [r, secondsCell] of [[21, "B20"], [24, "B23"], [27, null], [30, null], [33, null]]) {{
    const seconds = r === 27 || r === 33 ? 18000 : r === 30 ? 435000 : num(secondsCell);
    set(`D${{r}}`, fixed(num("D10") * seconds * num(`C${{r}}`)));
    if (r !== 30) set(`F${{r}}`, fixed(num("F10") * num(`E${{r}}`) * seconds));
    set(`H${{r}}`, fixed(num("H10") * num(`G${{r}}`) * monthlySeconds));
    if (r !== 30) set(`J${{r}}`, fixed(num("J10") * num(`I${{r}}`)));
    if (r !== 30) set(`L${{r}}`, fixed(num("L10") * num(`K${{r}}`)));
    set(`O${{r}}`, fixed(num(`D${{r}}`) + num(`F${{r}}`) + num(`H${{r}}`) + num(`J${{r}}`) + num(`N${{r}}`) + num(`L${{r}}`)));
  }}
  set("B20", fixed(num("B62") + 18000, 2));
  set("B23", fixed(num("B62") + 18000, 2));
  set("O34", fixed(num("O16") + num("O18") + num("O21") + num("O24") + num("O27") + num("O30") + num("O33")));

  set("K43", fixed(2.8 * num("J43"), 2));
  set("L43", fixed(num("J43") * 2.8, 2));
  set("M43", fixed(170 * num("J43"), 2));
  set("N43", fixed(num("J43") * 0.4, 2));
  set("O43", fixed(num("K43") * 6, 2));
  set("B44", compact(50 * 5));
  set("B45", compact(num("B43") + 1500));
  set("B46", compact(1500 * 4));
  set("B47", compact((300 + 50) + 2 * (300 + 50) + 3 * (300 + 50) + 4 * (300 + 50)));
  set("B48", compact(num("B44") + num("B45") + num("B46") + num("B47")));
  set("B49", fixed(num("B48") / 5, 2));
  set("G50", fixed(num("F50") * num("B58") / 1000000));
  set("G51", fixed(num("F51") * num("B59") / 1000000));
  set("G52", fixed(num("F52") * num("B67") / 1000000));
  set("B53", compact((num("B52") + num("B51")) * 5));
  set("G53", fixed(num("G50") + num("G51") + num("G52")));
  set("B56", compact(num("B53") + num("B48")));
  set("B57", fixed(num("B55") / num("B56"), 2));
  set("B58", compact(num("B57") * num("B48")));
  set("B59", compact(num("B57") * num("B53")));
  set("B60", compact(num("B57") * 5));
  set("B61", compact(5 * 60));
  set("B62", fixed(num("B61") * num("B57"), 2));
  set("C62", fixed(num("B62") / (60 * 60), 2));
  set("B63", fixed(num("B49") + num("B52") + num("B51"), 2));
  set("B65", compact(num("B43")));
  set("B66", compact(num("B57") * 4));
  set("B67", compact(num("B66") * num("B65")));
  set("F56", fixed(num("C62"), 2));
  set("G57", fixed(num("F56") * num("F55") * num("B65") / 1000000));
  set("G58", fixed(num("G57") + num("G53")));
  set("M47", fixed(num("O34")));
  set("N46", fixed(num("M46") * num("M51")));
  set("N47", fixed(num("M47") * num("M51")));
  set("M48", fixed(num("M46") - num("M47")));
  set("N48", fixed(num("M48") * num("M51")));
  set("N49", fixed(num("M49")));
  set("M50", fixed(num("M49") * num("M48")));
  set("N50", fixed(num("M50") * num("M51")));
  set("B72", fixed(num("B55") / num("B71"), 2));
}}
document.querySelectorAll("[contenteditable=true]").forEach(el => el.addEventListener("input", recalc));
document.querySelectorAll("[data-dropdown-cell]").forEach(el => el.addEventListener("change", recalc));
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
