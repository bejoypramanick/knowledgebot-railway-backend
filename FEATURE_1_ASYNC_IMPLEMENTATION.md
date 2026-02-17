# Feature 1: Async KB Processing Queue - Implementation Summary

## Status: ✅ BACKEND COMPLETE - Frontend updates required

This document summarizes the implementation of async file uploads and website scraping using FastAPI's BackgroundTasks.

---

## What's Been Implemented

### 1. Database Schema Updates ✅
**File**: `/sql/database_schema.sql`

Added two new columns to both `file_uploads` and `scraped_websites` tables:
```sql
processing_status VARCHAR(20) DEFAULT 'pending'
  CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed'))
error_message TEXT
```

Added indexes:
- `idx_file_uploads_processing_status` - for polling queries
- `idx_file_uploads_processing_pending` - optimized for pending/processing items
- `idx_scraped_websites_processing_status` - for polling queries
- `idx_scraped_websites_processing_pending` - optimized for pending/processing items

### 2. Knowledgebase Ingestion Service ✅
**File**: `/knowledgebase_ingestion/service/ingestion_service.py`

#### New Functions:
1. **`update_processing_status(file_id, status, error_message, table_name)`**
   - Updates processing status in database
   - Called during background task execution

2. **`process_file_upload_background(...)`**
   - Core async background task for file processing
   - Handles HTML, Docling (PDF/DOCX), and text files
   - Updates status to "processing" → "completed" or "failed"
   - Updates database with Gemini metadata on success

3. **`upload_file_async(file, display_name, user_email, background_tasks)`**
   - Returns immediately with status='pending'
   - Creates DB record with minimal data
   - Dispatches background task for actual processing
   - Returns file ID for frontend polling

### 3. Knowledgebase Ingestion Router ✅
**File**: `/knowledgebase_ingestion/routers/router.py`

#### New Endpoints:
1. **`POST /upload/async`**
   - Async upload endpoint with BackgroundTasks
   - Returns immediately with pending status
   - Takes same parameters as regular upload

2. **`GET /status`**
   - Get all pending/processing items (files and websites)
   - Returns list of files and websites with status
   - Useful for initial load to see all processing items

3. **`GET /status/{item_id}`**
   - Get status of single file or website
   - Returns item details including processing_status and error_message
   - Supports polling to track progress

### 4. Website Crawling Service ✅
**File**: `/website_crawling/service/website_service.py`

#### New Functions:
1. **`update_website_processing_status(website_id, status, error_message)`**
   - Updates website processing status in database

2. **`scrape_website_background(website_id, url, options)`**
   - Core async background task for website scraping
   - Calls existing `scrape_website()` method
   - Updates status to "processing" → "completed" or "failed"

3. **`scrape_website_async(url, options, background_tasks)`**
   - Returns immediately with status='pending'
   - Creates DB record with website URL and domain
   - Dispatches background task for actual scraping
   - Returns website ID for frontend polling

### 5. Website Crawling Router ✅
**File**: `/website_crawling/routers/router.py`

#### New Endpoint:
1. **`POST /async`**
   - Async website scraping endpoint with BackgroundTasks
   - Returns immediately with pending status
   - Supports single URL or comma-separated list of URLs
   - Takes same parameters as regular scrape endpoint

---

## API Contract

### File Upload Flow

**Step 1: Initiate Upload**
```bash
POST /api/v1/gateway/knowledgebase/upload/async
Content-Type: multipart/form-data

file: <binary>
display_name: optional_display_name

RESPONSE (200):
{
  "success": true,
  "message": "File upload queued for processing",
  "file": {
    "id": "123",
    "original_filename": "document.pdf",
    "display_name": "My Document",
    "size_bytes": "1048576",
    "mime_type": "application/pdf",
    "processing_status": "pending",
    "created_at": "2026-02-17T10:00:00Z"
  }
}
```

**Step 2: Poll Status**
```bash
GET /api/v1/gateway/knowledgebase/status/123

RESPONSE (200):
{
  "success": true,
  "type": "file",
  "id": "123",
  "name": "document.pdf",
  "processing_status": "processing",  // pending → processing → completed/failed
  "error_message": null,
  "created_at": "2026-02-17T10:00:00Z",
  "updated_at": "2026-02-17T10:00:30Z"
}
```

### Website Scraping Flow

**Step 1: Initiate Scrape**
```bash
POST /api/v1/gateway/webcrawl/async
Content-Type: application/json

{
  "url": "https://example.com/sitemap.xml",
  "max_depth": 2,
  "replace_existing": false,
  ...other options...
}

RESPONSE (200):
{
  "success": true,
  "message": "Website scraping queued for processing",
  "website": {
    "id": "456",
    "url": "https://example.com/sitemap.xml",
    "processing_status": "pending",
    "created_at": "2026-02-17T10:00:00Z"
  }
}
```

**Step 2: Poll Status**
```bash
GET /api/v1/gateway/knowledgebase/status/456

RESPONSE (200):
{
  "success": true,
  "type": "website",
  "id": "456",
  "name": "https://example.com/sitemap.xml",
  "processing_status": "completed",
  "error_message": null,
  "created_at": "2026-02-17T10:00:00Z",
  "updated_at": "2026-02-17T10:00:45Z"
}
```

### Get All Processing Items
```bash
GET /api/v1/gateway/knowledgebase/status

RESPONSE (200):
{
  "success": true,
  "files": [
    {
      "id": "123",
      "type": "file",
      "name": "document.pdf",
      "processing_status": "processing",
      "error_message": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ],
  "websites": [
    {
      "id": "456",
      "type": "website",
      "name": "https://example.com",
      "processing_status": "pending",
      "error_message": null,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

---

## Frontend Implementation Required

### 1. Update KnowledgeBaseManagement.tsx

**Change the uploadFiles method to use async endpoint:**
```typescript
// OLD: POST /upload (blocks until processing complete)
// NEW: POST /upload/async (returns immediately with pending status)

const uploadFilesAsync = async (files: File[]): Promise<any> => {
  const results = [];
  const headers = await this.getAuthHeaders();

  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch(`${this.baseUrl}/upload/async`, {
      method: 'POST',
      headers: headers,
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    results.push(await response.json());
  }

  return results;
};
```

### 2. Add Status Polling Hook

Create `useProcessingStatus.ts` hook:
```typescript
const useProcessingStatus = (itemIds: string[]) => {
  const [statuses, setStatuses] = useState({});
  const [isPolling, setIsPolling] = useState(false);

  useEffect(() => {
    if (!itemIds || itemIds.length === 0) return;

    const hasProcessing = Object.values(statuses).some(
      (status: any) => status.processing_status === 'processing' || status.processing_status === 'pending'
    );

    if (!hasProcessing) {
      setIsPolling(false);
      return;
    }

    setIsPolling(true);
    const interval = setInterval(async () => {
      for (const itemId of itemIds) {
        const response = await fetch(`/api/v1/gateway/knowledgebase/status/${itemId}`);
        const data = await response.json();
        setStatuses(prev => ({
          ...prev,
          [itemId]: data
        }));
      }
    }, 5000); // Poll every 5 seconds

    return () => clearInterval(interval);
  }, [itemIds, statuses]);

  return statuses;
};
```

### 3. Update UI to Show Processing Status

In DocumentList component, add status icons:
```typescript
// pending/processing: Animated spinner (Loader2 from lucide)
// completed: Green checkmark (CheckCircle2)
// failed: Red X with tooltip (XCircle)

const renderStatusIcon = (status: string, errorMessage?: string) => {
  switch(status) {
    case 'pending':
    case 'processing':
      return (
        <Loader2 className="w-4 h-4 text-yellow-500 animate-spin"
          title="Processing..." />
      );
    case 'completed':
      return (
        <CheckCircle2 className="w-4 h-4 text-green-500"
          title="Processing complete" />
      );
    case 'failed':
      return (
        <Tooltip>
          <TooltipTrigger>
            <XCircle className="w-4 h-4 text-red-500" />
          </TooltipTrigger>
          <TooltipContent>{errorMessage || 'Processing failed'}</TooltipContent>
        </Tooltip>
      );
  }
};
```

### 4. Update Upload Handler

When user uploads files:
1. Call `/upload/async` endpoint
2. Immediately add items to table with status='pending'
3. Start polling `/status/{id}` every 5 seconds
4. Update UI when status changes
5. Stop polling when all items are completed/failed

Example flow:
```typescript
const handleFileUpload = async (files: File[]) => {
  // 1. Call async upload
  const uploadResults = await uploadFilesAsync(files);

  // 2. Add to table immediately with pending status
  const newItems = uploadResults.map(result => ({
    ...result.file,
    processing_status: 'pending'
  }));
  setFiles([...files, ...newItems]);

  // 3. Start polling
  const fileIds = uploadResults.map(r => r.file.id);
  startPollingStatus(fileIds);
};

const startPollingStatus = (itemIds: string[]) => {
  const statuses = useProcessingStatus(itemIds);

  // Update items in table as status changes
  setFiles(prevFiles =>
    prevFiles.map(file => ({
      ...file,
      processing_status: statuses[file.id]?.processing_status || file.processing_status,
      error_message: statuses[file.id]?.error_message
    }))
  );
};
```

---

## Key Design Decisions

### 1. No Redis/Celery
- Using FastAPI's built-in `BackgroundTasks`
- Simple, zero-infrastructure, works natively with asyncio
- Status tracked in PostgreSQL (no separate job queue)
- Suitable for moderate traffic; can add Redis later if needed

### 2. Polling Over WebSocket
- Frontend polls every 5 seconds instead of WebSocket
- Simple, stateless, works with Railway deployment
- Lower latency acceptable (5 second polling window)
- Can be upgraded to WebSocket later

### 3. Database Status Storage
- Single source of truth is PostgreSQL
- All status information persists
- No in-memory job queue that could be lost
- Easy to query historical processing

### 4. Immediate Feedback
- File/website appears in table immediately with 'pending' status
- Frontend can show spinner icon while processing
- User sees immediate feedback, not "processing..." loading screen

---

## Migration Steps for Deployment

1. **Deploy database schema changes**
   ```bash
   # Run migration to add processing_status columns
   psql -d knowledgebot < migrations/add_processing_status.sql
   ```

2. **Deploy backend code**
   - New async endpoints go live
   - Old synchronous endpoints still work (backward compatible)

3. **Update frontend**
   - Change upload to use `/upload/async`
   - Change scrape to use `/async`
   - Add polling logic
   - Update UI with status icons

4. **Verify**
   - Test single file upload → shows pending → processing → completed
   - Test website scrape → shows pending → processing → completed
   - Test error handling → shows pending → failed with error message
   - Test status polling with `/status` endpoint

---

## Testing Checklist

- [ ] Upload file via `/upload/async` → returns immediately
- [ ] Poll `/status/{id}` → shows pending → processing → completed
- [ ] Upload invalid file → status shows as pending then failed with error
- [ ] Upload large file → status updates as processing
- [ ] Scrape sitemap via `/async` → returns immediately
- [ ] Poll `/status/{id}` for website → shows processing → completed
- [ ] Poll `/status` (no ID) → shows all processing items
- [ ] Network interruption during polling → resumes polling on next click
- [ ] Multiple concurrent uploads → all show in table with correct status
- [ ] Refresh page → previous uploads still show with current status

---

## Next Steps

1. **Update frontend** (as documented above)
2. **Test end-to-end** in development/staging
3. **Deploy to Railway**
4. **Monitor logs** for any processing errors
5. **Consider enhancements**:
   - WebSocket for real-time updates (future)
   - Redis for distributed processing (if scaling needed)
   - Retry logic for failed processing (current: manual retry via re-upload)
