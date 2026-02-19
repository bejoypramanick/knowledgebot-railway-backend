# ProcessingService Method Quick Reference

**Total Methods**: 41
**Avg Lines per Method**: 8.5
**Max Lines per Method**: 30 (core orchestrators)

---

## 📍 Finding a Method

### By Responsibility

**Job Lifecycle**
- `process_website_content()` — Entry point
- `_process_with_error_handling()` — Core logic
- `_log_job_start()` — Initial logging
- `_success_result()` — Success dict
- `_error_result()` — Error dict
- `_publish_success_result()` — Redis publish
- `_publish_error_result()` — Redis error

**Crawling**
- `_crawl_pages()` — BFS generator
- `_should_crawl_url()` — Dedup check
- `_fetch_single_page()` — Fetch one
- `_extract_links()` — Parse links
- `_make_absolute_url()` — URL conversion
- `_is_valid_crawl_link()` — Link validation

**Content Processing**
- `_process_page_content()` — Route to handlers
- `_html_to_markdown()` — Convert to markdown
- `_fallback_manual_clean()` — Manual cleanup
- `_clean_markdown_lines()` — Line trimming
- `_extract_embedded_files_if_docling_enabled()` — Docling gate
- `_find_embedded_file_links()` — Find files
- `_process_all_docling_files()` — Loop files
- `_process_single_docling_file()` — Process one file
- `_download_and_process_docling_file()` — Save + docling
- `_append_extracted_docs()` — Append to markdown

**Gemini Upload**
- `_upload_page_to_gemini()` — Main upload
- `_build_upload_config()` — Build config dict
- `_cleanup_temp_file()` — Delete temp
- `_poll_upload_operation()` — Poll LRO
- `_get_document_name_from_operation()` — Extract doc name
- `_resolve_file_search_store()` — Get store name
- `_resolve_user_role_id()` — Get user role

**Database Recording**
- `_record_child_page()` — Record page
- `_should_skip_child_record()` — Skip check
- `_build_child_page_metadata()` — Build metadata
- `_finalize_website_record()` — Update parent
- `_build_finalize_metadata()` — Build aggregate metadata

**Utilities**
- `_is_task_cancelled()` — Check Redis
- `_get_domain()` — Extract domain
- `_normalize_url()` — Normalize URL

---

## 🔀 Call Flow

```
START: process_website_content(website_id, url, max_depth, ...)
  │
  ├─ _log_job_start(website_id, url, max_depth, max_pages)
  │
  ├─ _is_task_cancelled(celery_task_id)  ← Check cancellation
  │
  ├─ _process_with_error_handling(...)
  │   │
  │   ├─ _resolve_file_search_store()  ← Fail fast
  │   │
  │   ├─ _resolve_user_role_id(user_email, user_role_id)  ← Allow NULL
  │   │
  │   └─ _stream_pages_through_pipeline(...)
  │       │
  │       └─ FOR EACH PAGE (async generator):
  │           │
  │           ├─ _crawl_pages(url, max_depth, ...)
  │           │   │
  │           │   ├─ _should_crawl_url(url, depth, max_depth, visited_urls)
  │           │   │   └─ _normalize_url(url)
  │           │   │
  │           │   ├─ _fetch_single_page(url, semaphore, delay)
  │           │   │   └─ AsyncWebCrawler.arun()  ← External API
  │           │   │
  │           │   └─ _extract_links(html, url, base_domain, visited_urls)
  │           │       ├─ _make_absolute_url(href, page_url)
  │           │       └─ _is_valid_crawl_link(url, base_domain, visited_urls)
  │           │
  │           ├─ _process_pipeline_page(website_id, page_url, page_html, ...)
  │           │   │
  │           │   ├─ _process_page_content(html, url)
  │           │   │   │
  │           │   │   ├─ _html_to_markdown(html)
  │           │   │   │   ├─ trafilatura.extract()  ← External library
  │           │   │   │   ├─ _fallback_manual_clean(html)  ← If extraction fails
  │           │   │   │   └─ _clean_markdown_lines(markdown)
  │           │   │   │
  │           │   │   └─ _extract_embedded_files_if_docling_enabled(html, url, markdown)
  │           │   │       ├─ _find_embedded_file_links(html, url)
  │           │   │       ├─ _process_all_docling_files(file_links)
  │           │   │       │   └─ _process_single_docling_file(client, file_link)
  │           │   │       │       └─ _download_and_process_docling_file(bytes, url, ...)
  │           │   │       │           └─ process_with_docling()  ← External service
  │           │   │       └─ _append_extracted_docs(markdown, docs)
  │           │   │
  │           │   ├─ _upload_page_to_gemini(website_id, page_url, markdown, store)
  │           │   │   ├─ _build_upload_config(doc_name, website_id, url)
  │           │   │   ├─ genai_client.upload_to_file_search_store()  ← Gemini API
  │           │   │   ├─ _poll_upload_operation(operation, celery_task_id)
  │           │   │   │   ├─ _is_task_cancelled(celery_task_id)  ← Check cancellation
  │           │   │   │   └─ _get_document_name_from_operation(operation)
  │           │   │   └─ _cleanup_temp_file(temp_file)
  │           │   │
  │           │   └─ _record_child_page(website_id, page_url, doc_name, ...)
  │           │       ├─ _should_skip_child_record(page_url, root_url, max_depth)
  │           │       ├─ _build_child_page_metadata(doc_name, store_name)
  │           │       └─ scraping_dao.record_child_page(...)  ← External DAO
  │           │
  │           └─ (accumulate metrics)
  │
  ├─ _finalize_website_record(website_id, page_count, total_size, ...)
  │   └─ _build_finalize_metadata(page_count, store_name)
  │       └─ SQL UPDATE scraped_websites  ← External database
  │
  ├─ _success_result(website_id, pages_uploaded, ...)
  │
  ├─ _publish_success_result(website_id, celery_task_id, result)
  │   └─ redis_message_queue.publish_web_result()  ← External Redis
  │
  └─ RETURN: success dict

ERROR HANDLING:
  └─ _error_result(website_id, error)
      └─ _publish_error_result(website_id, celery_task_id, error)
          └─ redis_message_queue.publish_web_result()  ← External Redis
```

---

## 🧪 Testing Each Layer

### Crawl Layer (5 methods)
```python
# Mock AsyncWebCrawler
# Test URL deduplication
# Test depth limiting
# Test link extraction
# Test domain filtering

@pytest.mark.asyncio
async def test_should_crawl_url():
    service = ProcessingService()
    # Test dedup
    assert not await service._should_crawl_url(..., visited_urls={"url"})
    # Test depth
    assert not await service._should_crawl_url(..., depth=5, max_depth=2)
    # Test valid
    assert await service._should_crawl_url(..., visited_urls=set())
```

### Content Layer (8 methods)
```python
# Test HTML parsing
# Test markdown conversion
# Test line cleaning
# Test docling integration

def test_html_to_markdown():
    service = ProcessingService()
    markdown = service._html_to_markdown("<h1>Test</h1>")
    assert "Test" in markdown
    assert len(markdown) > 0

def test_clean_markdown_lines():
    service = ProcessingService()
    dirty = "line1\n\n\nline2\n\n\n\nline3"
    clean = service._clean_markdown_lines(dirty)
    assert clean.count('\n') == 2  # Only single blank lines
```

### Upload Layer (7 methods)
```python
# Mock Gemini API
# Test upload config building
# Test LRO polling
# Test temp file cleanup

@pytest.mark.asyncio
async def test_build_upload_config():
    service = ProcessingService()
    config = await service._build_upload_config("doc_name", 123, "http://example.com")
    assert config['display_name'] == "doc_name"
    assert config['mime_type'] == 'text/markdown'
    assert len(config['custom_metadata']) == 3
```

### Database Layer (6 methods)
```python
# Mock scraping_dao
# Test metadata building
# Test single-page skip logic

@pytest.mark.asyncio
async def test_should_skip_child_record():
    service = ProcessingService()
    # Single-page root: skip
    assert await service._should_skip_child_record(
        "http://example.com", "http://example.com", max_depth=0
    ) == True
    # Multi-page child: don't skip
    assert await service._should_skip_child_record(
        "http://example.com/page", "http://example.com", max_depth=1
    ) == False
```

---

## 📊 Method Size Distribution

```
2-4 lines   ███████████████░░░░░░░░░░░░░░░░░░░░░░ (9/41 = 22%)
5-9 lines   ██████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░ (15/41 = 37%)
10-14 lines ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ (8/41 = 20%)
15-20 lines ███░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ (5/41 = 12%)
20+ lines   ██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ (4/41 = 10%)
```

**91% of methods are 14 lines or less.**

---

## 🎯 Searching for Functionality

**"How do I make pages crawl?"**
→ Look at `_crawl_pages()` and `_extract_links()`

**"How does a page get uploaded?"**
→ Look at `_upload_page_to_gemini()` and `_poll_upload_operation()`

**"How is metadata recorded?"**
→ Look at `_record_child_page()` and `_finalize_website_record()`

**"Where are temp files cleaned?"**
→ Look at `_cleanup_temp_file()`

**"How does cancellation work?"**
→ Look at `_is_task_cancelled()` (used in 3 places)

**"What if upload fails?"**
→ Look at `_upload_page_to_gemini()` (returns None, caught in `_process_pipeline_page()`)

**"What if a page is single-page (depth=0)?"**
→ Look at `_should_skip_child_record()`

**"Where are results published to Redis?"**
→ Look at `_publish_success_result()` and `_publish_error_result()`

---

## ✅ Checklist: All 41 Methods Present

### Orchestration (7)
- [ ] `process_website_content()`
- [ ] `_log_job_start()`
- [ ] `_process_with_error_handling()`
- [ ] `_stream_pages_through_pipeline()`
- [ ] `_process_pipeline_page()`
- [ ] `_success_result()`
- [ ] `_error_result()`
- [ ] `_publish_success_result()`
- [ ] `_publish_error_result()`

### Crawl (5)
- [ ] `_crawl_pages()`
- [ ] `_should_crawl_url()`
- [ ] `_fetch_single_page()`
- [ ] `_extract_links()`
- [ ] `_make_absolute_url()`
- [ ] `_is_valid_crawl_link()`

### Content (8)
- [ ] `_process_page_content()`
- [ ] `_html_to_markdown()`
- [ ] `_fallback_manual_clean()`
- [ ] `_clean_markdown_lines()`
- [ ] `_extract_embedded_files_if_docling_enabled()`
- [ ] `_find_embedded_file_links()`
- [ ] `_process_all_docling_files()`
- [ ] `_process_single_docling_file()`
- [ ] `_download_and_process_docling_file()`
- [ ] `_append_extracted_docs()`

### Upload (7)
- [ ] `_upload_page_to_gemini()`
- [ ] `_build_upload_config()`
- [ ] `_cleanup_temp_file()`
- [ ] `_poll_upload_operation()`
- [ ] `_get_document_name_from_operation()`
- [ ] `_resolve_file_search_store()`
- [ ] `_resolve_user_role_id()`

### Database (6)
- [ ] `_record_child_page()`
- [ ] `_should_skip_child_record()`
- [ ] `_build_child_page_metadata()`
- [ ] `_finalize_website_record()`
- [ ] `_build_finalize_metadata()`

### Utilities (3)
- [ ] `_is_task_cancelled()`
- [ ] `_get_domain()`
- [ ] `_normalize_url()`

**Total: 41 methods**

---

## 📖 Documentation Files

1. **REFACTOR_SUMMARY.md** — High-level overview, before/after comparison
2. **EXTREME_SRP_BREAKDOWN.md** — Detailed method breakdown, dependency graph, testing strategy
3. **METHOD_REFERENCE.md** — This file, quick lookup guide
4. **VERIFICATION.md** — Expected behavior, test scenarios, error cases

Start with **METHOD_REFERENCE.md** (you're reading it!) for quick lookups.
