# Child Page Citations Implementation Plan

## Problem Statement

When scraping websites with child pages, the current implementation:
- ❌ Combines all pages into a single string
- ❌ Stores only the parent domain URL in the database
- ❌ Loses track of which content belongs to which child page
- ❌ Cannot cite individual child pages in chatbot responses

## Current Behavior Analysis

### ✅ What's Working (Sitemap Approach)
```python
# In _scrape_urls_from_sitemap():
scraped_data.append({
    "index": result["index"],
    "url": result["url"],           # Individual page URL preserved
    "text": result["text"]          # Individual page content
})

# Each page uploaded separately with its own URL
record_id = await record_scraped_metadata(
    url=page_url,  # Individual URL, not parent
    scraped_urls=[page_url],
    file_search_metadata=gemini_result.get("file_search_metadata")
)
```

Result: Each page = separate database record = can be cited individually ✅

### ❌ What's NOT Working (Regular Multi-Page Crawl)
```python
# In _scrape_with_crawl4ai() and _scrape_with_httpx():
all_content.append(f"\n\n--- Page: {current_url} ---\n\n{content}")

# Single combined upload
gemini_result = await upload_content_to_gemini(
    content=combined_content,  # All pages merged
    url=url,  # Only parent URL, not child URLs
    title=title
)

# Single database record for all pages
record_id = await record_scraped_metadata(
    url=url,  # Parent URL only
    scraped_urls=result.get("scraped_urls", [url]),  # URLs tracked but not used
    pages_scraped=result.get("pages_scraped", 1)
)
```

Result: All pages combined = single database record = can't cite individual pages ❌

---

## Solution: Unify Approaches

Make **regular multi-page crawling work like sitemap scraping** by uploading each page individually.

### Implementation Steps

#### Step 1: Modify `_scrape_with_crawl4ai()` and `_scrape_with_httpx()`

**Change from:**
```python
all_content = []  # Combine everything
# ... scraping loop ...
all_content.append(f"\n\n--- Page: {url} ---\n\n{content}")
# End with single combined string
combined_content = "\n".join(all_content)
```

**Change to:**
```python
scraped_data = []  # Track individual pages
# ... scraping loop ...
scraped_data.append({
    "url": current_url,
    "text": content,
    "title": title  # Extract page-specific title
})
# End with list of page objects
```

#### Step 2: Handle Single vs. Multi-Page Uploads

**In `scrape_website()` method:**

```python
# Check if multi-page scraping
if result.get("pages_scraped", 1) > 1:
    # Upload each page individually (like sitemap)
    scraped_data = result.get("scraped_data", [])
    for page in scraped_data:
        # Each page gets own database record
        await upload_and_record_page(
            url=page["url"],
            content=page["text"],
            title=page.get("title")
        )
else:
    # Single page - upload normally
    await upload_content_to_gemini(...)
```

#### Step 3: Update AI Service for Per-Page Metadata

**In `upload_content_to_gemini()`:**

```python
# Store INDIVIDUAL page URL in metadata
custom_metadata = [
    {'key': 'original_url', 'string_value': url},
    {'key': 'page_type', 'string_value': 'child_page' if depth > 0 else 'root'},
    {'key': 'depth', 'string_value': str(depth)},
    {'key': 'user_email', 'string_value': user_email}
]
```

#### Step 4: Database Metadata Structure

**Store in metadata JSONB:**

```json
{
  "type": "file_search",
  "file_search_store_name": "knowledgebot-search-store",
  "document_name": "files/abc123",
  "original_url": "https://example.com/page1",
  "page_type": "child_page",
  "depth": 1,
  "uploaded_at": "2024-02-12T10:30:00Z",
  "parent_domain": "example.com"
}
```

#### Step 5: Store Child URLs List

**Add to scraped_websites metadata:**

```python
metadata["scraped_urls"] = result.get("scraped_urls", [url])
metadata["child_page_urls"] = [
    page["url"] for page in result.get("scraped_data", [])
]
metadata["total_child_pages"] = len(result.get("scraped_data", []))
```

---

## Detailed Changes Required

### File 1: `website_crawling/service/website_service.py`

#### Change 1: Update `_scrape_with_crawl4ai()` (lines 315-386)

```python
async def _scrape_with_crawl4ai(
    self,
    url: str,
    max_pages: int,
    max_depth: int,
    timeout: int,
    delay_between_requests: float = 0,
    max_concurrent: int = 10
) -> Dict[str, Any]:
    """Scrape using crawl4ai library - preserve individual page data."""
    scraped_data = []  # NEW: Track individual pages
    scraped_urls: Set[str] = set()
    urls_to_scrape = [(url, 0)]
    title = "Untitled"
    semaphore = asyncio.Semaphore(max_concurrent)

    try:
        async with AsyncWebCrawler(verbose=False) as crawler:
            while urls_to_scrape and len(scraped_urls) < max_pages:
                current_url, depth = urls_to_scrape.pop(0)

                if current_url in scraped_urls:
                    continue

                logger.info(f"📄 Scraping page {len(scraped_urls) + 1}/{max_pages}: {current_url} (depth={depth})")

                try:
                    async with semaphore:
                        result = await asyncio.wait_for(
                            crawler.arun(url=current_url),
                            timeout=timeout
                        )

                        if result.success:
                            scraped_urls.add(current_url)

                            # Get content
                            content = result.markdown or result.cleaned_html or result.html or ""
                            if content:
                                # NEW: Store individual page data
                                page_title = ""
                                if len(scraped_urls) == 1 and hasattr(result, 'title') and result.title:
                                    title = result.title
                                    page_title = result.title

                                scraped_data.append({
                                    "url": current_url,
                                    "text": content,
                                    "title": page_title,
                                    "depth": depth
                                })

                            # Extract links for further crawling
                            if depth < max_depth and len(scraped_urls) < max_pages:
                                links = extract_links_from_result(result, current_url)
                                for link in links:
                                    if link not in scraped_urls and (link, depth + 1) not in urls_to_scrape:
                                        urls_to_scrape.append((link, depth + 1))

                        else:
                            logger.warning(f"⚠️ Failed to scrape {current_url}: {result.error_message}")

                        # Apply delay between requests
                        if delay_between_requests > 0 and urls_to_scrape:
                            logger.info(f"⏳ Waiting {delay_between_requests}s before next request")
                            await asyncio.sleep(delay_between_requests)

                except asyncio.TimeoutError:
                    logger.warning(f"⏱️ Timeout scraping {current_url}")
                except Exception as e:
                    logger.warning(f"⚠️ Error scraping {current_url}: {e}")

        # NEW: Return both combined and individual data
        combined_content = "\n".join([
            f"\n\n--- Page: {item['url']} ---\n\n{item['text']}"
            for item in scraped_data
        ])

        return {
            "success": len(scraped_urls) > 0,
            "content": combined_content,
            "title": title,
            "pages_scraped": len(scraped_urls),
            "scraped_urls": list(scraped_urls),
            "scraped_data": scraped_data  # NEW: Individual page data
        }

    except Exception as e:
        logger.error(f"❌ crawl4ai error: {e}")
        return {
            "success": False,
            "error": str(e)
        }
```

#### Change 2: Update `_scrape_with_httpx()` (lines 388-499)

Same pattern as above - add `scraped_data` list and store individual pages.

#### Change 3: Update `scrape_website()` method (lines 51-313)

```python
# For non-sitemap, multi-page crawls: upload individually like sitemap
scraped_data = result.get("scraped_data", [])

if scraped_data and len(scraped_data) > 1:
    # Multi-page crawl: upload each page individually
    logger.info(f"📋 Multi-page crawl detected: uploading {len(scraped_data)} pages individually")

    uploaded_files = []
    record_ids = []
    all_child_urls = []

    for page_data in scraped_data:
        page_url = page_data["url"]
        page_text = page_data["text"]
        page_title = page_data.get("title", "")
        page_depth = page_data.get("depth", 0)

        all_child_urls.append(page_url)

        try:
            # Upload individual page
            gemini_result = await upload_content_to_gemini(
                content=page_text,
                url=page_url,
                title=page_title,
                user_email=options.get("user_email")
            )

            # Record metadata for individual page
            record_id = await record_scraped_metadata(
                url=page_url,  # Use child page URL
                domain=urlparse(page_url).netloc.replace('www.', ''),
                title=page_title or page_url,
                content_length=len(page_text),
                pages_scraped=1,  # Each is a separate page
                gemini_file_name=gemini_result.get("file_name"),
                gemini_file_uri=gemini_result.get("file_uri"),
                gemini_state=gemini_result.get("state", "UNKNOWN"),
                scraped_urls=[page_url],
                scraping_config={
                    "max_pages": max_pages,
                    "max_depth": max_depth,
                    "page_depth": page_depth,
                    "source": "regular_crawl",
                    "parent_domain": urlparse(url).netloc,
                    "total_pages_in_crawl": len(scraped_data)
                },
                file_search_metadata=gemini_result.get("file_search_metadata")
            )

            uploaded_files.append({
                "url": page_url,
                "file_name": gemini_result.get("file_name"),
                "record_id": record_id,
                "depth": page_depth
            })
            record_ids.append(record_id)

        except Exception as e:
            logger.error(f"❌ Failed to upload page {page_url}: {e}")

    processing_time = time.perf_counter() - start_time

    return {
        "success": True,
        "job_id": f"job_{int(time.time())}",
        "url": url,  # Original domain URL
        "status": "completed",
        "pages_scraped": len(uploaded_files),
        "content_length": len(result["content"]),
        "title": result.get("title"),
        "uploaded_files": uploaded_files,
        "record_ids": record_ids,
        "processing_time_seconds": round(processing_time, 2),
        "scraped_urls": list(all_child_urls),  # All child URLs
        "parent_domain": urlparse(url).netloc
    }
else:
    # Single page: upload normally (existing code)
    ...
```

### File 2: `website_crawling/service/ai_service.py`

#### Update `upload_content_to_gemini()` to track page metadata

```python
# Lines 79-85: Add more metadata
config={
    'display_name': temp_filename,
    'custom_metadata': [
        {'key': 'original_url', 'string_value': url},
        {'key': 'user_email', 'string_value': user_email or 'admin'},
        {'key': 'page_type', 'string_value': 'child_page'},  # NEW
        {'key': 'source', 'string_value': 'website_scraping'}  # NEW
    ]
}
```

#### Update FileSearch metadata returned

```python
"file_search_metadata": {
    "type": "file_search",
    "file_search_store_name": file_search_store_name,
    "document_name": document_name,
    "original_url": url,  # Individual page URL
    "page_type": "child_page",  # NEW
    "uploaded_at": gemini_processed_at.isoformat() if gemini_processed_at else None
}
```

### File 3: `website_crawling/dao/scraping_dao.py`

#### Update `record_scraped_metadata()` to store child URLs

```python
# Lines 240-243: Store child URL list
if file_search_metadata:
    metadata["file_search_metadata"] = file_search_metadata
    logger.info(f"📝 [METADATA] Storing FileSearch info for {url}")

# NEW: Store child URLs in metadata
metadata["child_page_urls"] = scraped_urls if isinstance(scraped_urls, list) else [url]
metadata["total_child_pages"] = len(scraped_urls) if isinstance(scraped_urls, list) else 1
```

---

## Testing Strategy

### Test 1: Single Page Crawl
```
Input: https://example.com (1 page)
Expected:
  - 1 database record
  - URL = https://example.com
  - pages_scraped = 1
  - No child pages
```

### Test 2: Multi-Page Crawl (Depth=2)
```
Input: https://example.com (max_depth=2)
Expected:
  - N database records (one per page scraped)
  - Each record has its own child_page_url
  - metadata.child_page_urls = [all URLs]
  - Each page uploadable separately to Gemini
```

### Test 3: Sitemap Crawl
```
Input: https://example.com/sitemap.xml
Expected:
  - Each URL from sitemap = separate record
  - All records have correct child_page_urls
  - Can cite each page individually
```

### Test 4: Citation Retrieval
```
Chatbot question about content from https://example.com/page1
Expected chatbot response footer:
  Sources:
  - https://example.com/page1
  - https://example.com/page2
  (lists all pages that contributed to the answer)
```

---

## Database Metadata Example

### Before (Current):
```json
{
  "user_role_id": 1,
  "url": "https://example.com",
  "domain": "example.com",
  "pages_scraped": 3,
  "file_search_metadata": {
    "type": "file_search",
    "file_search_store_name": "knowledgebot-search-store",
    "document_name": "files/abc123",
    "uploaded_at": "2024-02-12T10:30:00Z"
  }
}
```

### After (Enhanced):
```json
{
  "user_role_id": 1,
  "url": "https://example.com",
  "domain": "example.com",
  "pages_scraped": 1,  # Each child page is separate record now
  "child_page_urls": ["https://example.com/page1"],
  "total_child_pages": 1,
  "file_search_metadata": {
    "type": "file_search",
    "file_search_store_name": "knowledgebot-search-store",
    "document_name": "files/xyz789",
    "original_url": "https://example.com/page1",  # Individual page
    "page_type": "child_page",
    "depth": 1,
    "uploaded_at": "2024-02-12T10:30:00Z"
  }
}
```

---

## Impact on Chatbot Citations

### Before:
```
Chatbot: "Based on the website content..."
Sources: example.com
(Can't tell which page the info came from)
```

### After:
```
Chatbot: "Based on the website content..."
Sources:
  - https://example.com/about
  - https://example.com/products
  - https://example.com/blog/article-1
(User knows exactly which pages were referenced)
```

---

## Implementation Checklist

- [ ] Add `scraped_data` list to crawl4ai method
- [ ] Add `scraped_data` list to httpx method
- [ ] Update scrape_website() to handle multi-page uploads individually
- [ ] Update upload_content_to_gemini() to include page metadata
- [ ] Update record_scraped_metadata() to store child URLs
- [ ] Update DAO to properly store all metadata
- [ ] Test single page crawl
- [ ] Test multi-page crawl
- [ ] Test sitemap crawl
- [ ] Verify database records have correct child_page_urls
- [ ] Test citation retrieval in chatbot
- [ ] Verify backward compatibility

---

## Summary

This implementation ensures that:
✅ Every child page gets its own database record
✅ Each page has its individual URL stored in metadata
✅ Pages are uploaded individually to FileSearch
✅ Chatbot can cite specific child pages
✅ Citation footer shows all contributing pages
✅ Works for both regular crawls and sitemaps

