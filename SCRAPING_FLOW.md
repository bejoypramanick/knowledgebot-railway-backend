# Website Scraping Flow - Simple Explanation

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  User clicks "Start Crawling"                                   │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  API Gateway receives request                                   │
│  → Sends to knowledgebase_ingestion service                     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  knowledgebase_ingestion dispatches Celery task                 │
│  → Task ID: abc123xyz                                           │
│  → Queued to Redis (DB 1: web_crawler queue)                    │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  API returns immediately to user                                │
│  Message: "Crawling started - click Refresh to see results"    │
└─────────────────────────────────────────────────────────────────┘


     ↓↓↓ BACKGROUND: Celery Worker Picks Up Task ↓↓↓


┌─────────────────────────────────────────────────────────────────┐
│  celery-web-worker (listening on Redis DB 1)                    │
│  Receives: scrape_website_task                                  │
│  Parameters: website_id=5, url="https://example.com", ...       │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│  ProcessingService.process_website_content() starts             │
│  Task ID: abc123xyz (for cancellation tracking)                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
             ┌───────────────┐
             │   SETUP PHASE │
             └───────┬───────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
    Log Job      Resolve Store  Resolve
    Started      (FileSearch)   User Role
                 [Fail Fast]    [Allow NULL]
```

---

## Detailed Scraping Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│  MAIN PIPELINE: Stream pages through per-page processing       │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
    ┌────────────────────────────────────┐
    │  FOR EACH PAGE (until max_pages)   │
    │  ↓ One page at a time ↓            │
    └────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
 STEP 1          STEP 2           STEP 3
 CRAWL           CONVERT          UPLOAD
    │                ▼                │
    │            ┌────────┐           │
    │            │ HTML   │           │
    │            │   ↓    │           │
    │            │Markdown│           │
    │            └────────┘           │
    │                ▼                │
    │          STEP 4: RECORD         │
    │          ↓ Database ↓           │
    │                ▼                │
    │        ┌─────────────┐          │
    │        │ Next Page?  │          │
    │        └──────┬──────┘          │
    │               │                 │
    │          YES ▼ NO              │
    │          Loop  Exit            │
    └─────────────────────────────────┘
```

---

## Step-by-Step: How ONE Page is Scraped

### Step 1️⃣: CRAWL (Fetch the page)

```
┌──────────────────────────────────────────────────┐
│ _crawl_pages()                                   │
│ Async generator: yields pages one-by-one        │
│                                                  │
│ BFS Queue: [(url, depth)]                       │
│ Visited Set: {normalized_urls}                  │
└──────────────┬───────────────────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
    ┌─────────┐   ┌──────────┐
    │ Pop URL │   │ Check:   │
    │ from    │   │ - Visited?
    │ queue   │   │ - Depth OK?
    │         │   └──────────┘
    └────┬────┘        ▲
         │         NO  │
         │ YES   ┌─────┘
         │       │
         ▼       ▼
    ┌─────────────────────┐
    │ _fetch_single_page()│
    │                     │
    │ AsyncWebCrawler     │
    │ arun(url)           │
    │                     │
    │ Returns: (url,html) │
    │         OR None     │
    └────────┬────────────┘
             │
    ┌────────┴──────────┐
    ▼                   ▼
SUCCESS            FAILED
(html OK)         (skip page)
    │                 │
    ▼                 ▼
Yield page         Return None
    │
    ▼
Extract links
(if depth < max)
    │
    ▼
Add to queue
    │
    ▼
Next iteration

┌─────────────────────────────────────┐
│ Result: (url, html)                 │
│ "https://example.com/about"         │
│ "<html>...</html>"                  │
└─────────────────────────────────────┘
```

### Step 2️⃣: CONVERT (HTML → Markdown)

```
┌──────────────────────────────────────────────────┐
│ _process_page_content(html, url)                │
└──────────────┬───────────────────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
    ┌──────────┐  ┌────────────────┐
    │ Convert  │  │ Extract        │
    │ to       │  │ Embedded Files │
    │ Markdown │  │ (if docling    │
    │          │  │  enabled)      │
    └────┬─────┘  └────────┬───────┘
         │                 │
         ▼                 ▼
    ┌──────────────────────────┐
    │ _html_to_markdown()      │
    │                          │
    │ 1. Trafilatura extract   │
    │ 2. Convert to markdown   │
    │ 3. Clean lines           │
    │ 4. Remove noise          │
    └────────┬─────────────────┘
             │
         ┌───┴───┐
         ▼       ▼
    SUCCESS  FALLBACK
             Manual
             clean
             │
    ┌────────┴────────┐
    ▼                 ▼
 # Heading        # Heading
 Paragraph        Paragraph
 ## Subhead       ## Subhead
 ...              ...

┌─────────────────────────────────┐
│ Result: Markdown string         │
│ "# About Us\n\nWe are..."       │
│ (5000 characters)               │
└─────────────────────────────────┘
```

**Optional Docling (if DOCLING_ENABLED=true)**:
```
┌────────────────────────────────────┐
│ _extract_embedded_files_...()      │
│                                    │
│ Find: PDF, DOCX, PPTX, etc links  │
└────────┬─────────────────────────┘
         │
     ┌───┴────┐
     ▼        ▼
 FOUND    NOT FOUND
 Files    → Return
    │       markdown
    ▼
Download
each file
    │
    ▼
Process
with
docling
service
    │
    ▼
Extract
text
    │
    ▼
Append
to
markdown
    │
    ▼
# Heading
Content
---
## Embedded Documents
### PDF Title
Content from PDF...
```

### Step 3️⃣: UPLOAD (Send to Gemini)

```
┌──────────────────────────────────────────────────┐
│ _upload_page_to_gemini(website_id, url,         │
│                        markdown, store_name)     │
└──────────────┬───────────────────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
    ┌────────┐   ┌──────────┐
    │ Create │   │ Build    │
    │ Temp   │   │ Upload   │
    │ File   │   │ Config   │
    │ (.md)  │   │          │
    └────┬───┘   └──────────┘
         │
         ▼
    ┌──────────────────────┐
    │ Call Gemini API:     │
    │ upload_to_file_      │
    │ search_store()       │
    │                      │
    │ Request sent →       │
    │ Get operation        │
    └────────┬─────────────┘
             │
    ┌────────┴──────────┐
    ▼                   ▼
SUCCESS            FAILED
 (Operation)        (None)
    │               │
    ▼               ▼
Poll LRO       Skip page
    │          Go to next
    ▼
Every 5s:
Check if done
    │
    ├─ Cancelled?
    │  YES → Return None
    │
    ├─ Timeout (5min)?
    │  YES → Return None
    │
    └─ Done?
       YES → Extract doc_name
             Return doc_name

┌─────────────────────────────────┐
│ Result: document_name           │
│ "documents/abc123def"           │
│ (stored in Gemini FileSearch)   │
└─────────────────────────────────┘
```

### Step 4️⃣: RECORD (Save to Database)

```
┌──────────────────────────────────────────────────┐
│ _record_child_page(website_id, page_url,        │
│                    doc_name, ...)                │
└──────────────┬───────────────────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
    ┌─────────┐  ┌──────────────┐
    │ Check:  │  │ Build        │
    │ Single  │  │ Metadata:    │
    │ page?   │  │ store_name,  │
    │         │  │ doc_name,    │
    │ (max_   │  │ uploaded_at  │
    │  depth= │  │              │
    │  0 and  │  └──────────────┘
    │ is root)│
    └────┬────┘
         │
    ┌────┴────┐
    ▼         ▼
   YES       NO
  Skip    Record
  this    child
  page    page
    │         │
    ▼         ▼
Return      Call DAO:
parent_id   record_child_page()
            (insert into DB)

┌─────────────────────────────────┐
│ Database: scraped_websites      │
│                                 │
│ ID    | parent_id | url | ...   │
│ ─────────────────────────────   │
│ 5     | NULL      | root        │ ← Parent
│ 6     | 5         | /about      │ ← Child 1
│ 7     | 5         | /contact    │ ← Child 2
│ 8     | 5         | /products   │ ← Child 3
└─────────────────────────────────┘
```

---

## Full Loop: Multiple Pages

```
Page 1: example.com
├─ FETCH: curl example.com
│         → <html>...</html>
├─ CONVERT: trafilatura + markdown
│          → "# Home\nWelcome..."
├─ UPLOAD: to Gemini FileSearch
│         → documents/page_1
├─ RECORD: insert into DB (row 6)
│
├─ METRICS: 5000 chars, 50KB
│
Page 2: example.com/about
├─ FETCH: curl example.com/about
│         → <html>...</html>
├─ CONVERT: trafilatura + markdown
│          → "# About Us\nWe are..."
├─ UPLOAD: to Gemini FileSearch
│         → documents/page_2
├─ RECORD: insert into DB (row 7)
│
├─ METRICS: 3000 chars, 30KB
│
Page 3: example.com/contact
├─ FETCH: curl example.com/contact
│         → <html>...</html>
├─ CONVERT: trafilatura + markdown
│          → "# Contact\nReach us..."
├─ UPLOAD: to Gemini FileSearch
│         → documents/page_3
├─ RECORD: insert into DB (row 8)
│
└─ METRICS: 2000 chars, 20KB
```

---

## After All Pages: Finalization

```
┌────────────────────────────────────────┐
│ _finalize_website_record()             │
│                                        │
│ Update parent record with:             │
│ - Total pages: 3                       │
│ - Total size: 100 KB (50+30+20)        │
│ - Total chars: 10,000 (5k+3k+2k)       │
│ - Status: completed                    │
│ - Store info: FileSearch metadata      │
└────────┬─────────────────────────────┘
         │
         ▼
    UPDATE scraped_websites
    SET pages_scraped = 3,
        file_size = 102400,
        char_count = 10000,
        processing_status = 'completed',
        metadata = {...}
    WHERE id = 5
```

---

## Publishing Results

```
┌────────────────────────────────────────┐
│ _publish_success_result()              │
│                                        │
│ Send to Redis:                         │
│ Topic: "web_results:abc123xyz"         │
│ Message: {                             │
│   "success": true,                     │
│   "page_count": 3,                     │
│   "total_size_bytes": 102400,          │
│   "total_char_count": 10000,           │
│   "processing_time_seconds": 45.2      │
│ }                                      │
└────────┬─────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────┐
│ UI (knowledgebot frontend)             │
│                                        │
│ Polling Redis or WebSocket:            │
│ "Crawling completed: 3 pages"          │
│                                        │
│ User clicks Refresh:                   │
│ Fetches knowledge base list            │
│ Shows newly scraped content            │
└────────────────────────────────────────┘
```

---

## Error Handling: What If Page Fails?

```
Page Upload Fails:
    │
    ├─ FETCH succeeds ✓
    ├─ CONVERT succeeds ✓
    ├─ UPLOAD fails ✗
    │  └─ _upload_page_to_gemini() returns None
    │
    └─ In _process_pipeline_page():
       if not doc_name:
           logger.warning("Upload failed, skipping")
           return None  ← Skip this page

       Next iteration:
       Process Page 4 normally

       Final metrics:
       pages_uploaded = 2 (only successful)
       total_size = 70KB (50KB + 20KB, not including failed page)
```

---

## Cancellation: Admin Clicks "Delete All"

```
Admin clicks "Delete All"
    │
    ▼
Delete All endpoint:
    ├─ Sets Redis flag: task_cancelled:abc123xyz
    └─ Clears task queue

celery-web-worker receives:
    │
    ├─ Checkpoint 1: Before crawl
    │  if cancelled: return error
    │
    ├─ Checkpoint 2: At BFS loop
    │  if cancelled: break generator
    │
    ├─ Checkpoint 3: At pipeline loop
    │  if cancelled: break pipeline
    │
    ├─ Checkpoint 4: During upload polling
    │  if cancelled: return None
    │
    └─ Result: Task stops, pages_uploaded = 2 (partial)
```

---

## Memory Efficiency: Key Difference

### OLD WAY (Batch):
```
Scrape 100 pages → memory: 500 pages in RAM
Convert 100 pages → memory: still 500 pages in RAM
Upload 100 pages → memory: still 500 pages in RAM
Record → finally released

Total memory at peak: ~16 MB
```

### NEW WAY (Streaming):
```
Page 1: Scrape → Convert → Upload → Record → Released from memory
        memory: 1 page

Page 2: Scrape → Convert → Upload → Record → Released from memory
        memory: 1 page

...

Total memory at peak: ~150 KB (same 5-8 pages being processed)
```

**Result**: 100x memory reduction ✅

---

## Complete Flow Summary

```
START
  │
  ├─ User clicks "Start Crawling"
  │
  ├─ API Gateway → knowledgebase_ingestion
  │
  ├─ Dispatch to Celery (Redis DB 1)
  │
  ├─ Return to user: "Crawling started"
  │
  └─ Background: celery-web-worker picks up task
                  │
                  ├─ Resolve FileSearch store
                  ├─ Resolve user_role_id
                  │
                  ├─ FOR EACH PAGE:
                  │   ├─ Fetch (crawl4ai)
                  │   ├─ Convert (trafilatura → markdown)
                  │   ├─ Upload (Gemini FileSearch)
                  │   └─ Record (database)
                  │
                  ├─ Finalize parent record
                  │
                  ├─ Publish to Redis
                  │
                  └─ UI Refresh shows new content

END
```

---

## Key Methods Called (In Order)

1. **process_website_content()** — Entry point
2. **_resolve_file_search_store()** — Get Gemini store (fail fast)
3. **_resolve_user_role_id()** — Get user ID (allow NULL)
4. **_stream_pages_through_pipeline()** — Main loop
   - **_crawl_pages()** — BFS generator
     - **_fetch_single_page()** — Crawl4ai
     - **_extract_links()** — Parse HTML
   - **_process_page_content()** — Route to handlers
     - **_html_to_markdown()** — Trafilatura
     - **_extract_embedded_files_if_docling_enabled()** — Docling (optional)
   - **_upload_page_to_gemini()** — Send to Gemini
     - **_poll_upload_operation()** — Wait for completion
   - **_record_child_page()** — Insert to database
5. **_finalize_website_record()** — Update parent
6. **_publish_success_result()** — Redis notification

**Total**: ~40 focused methods, each does one thing ✅
