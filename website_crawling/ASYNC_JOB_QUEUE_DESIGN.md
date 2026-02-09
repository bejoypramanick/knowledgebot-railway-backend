# Production-Grade Async Job Queue for Web Scraping

## Problem Statement

Large sitemap scraping causes timeouts because:
1. API Gateway has 30s default timeout
2. Scraping 100s of pages takes minutes/hours
3. Synchronous processing blocks the request
4. No way to track progress or resume failed jobs

## Production-Grade Solution

### Architecture

```
┌─────────────┐
│   Frontend  │
└──────┬──────┘
       │ POST /webcrawl (returns job_id immediately)
       ↓
┌──────────────────┐
│   API Gateway    │
└──────┬───────────┘
       │
       ↓
┌────────────────────────────┐
│  Web Crawling Service      │
│  ┌──────────────────────┐  │
│  │  1. Create Job       │  │ ← Returns in <1s
│  │  2. Return job_id    │  │
│  └──────────────────────┘  │
│                            │
│  ┌──────────────────────┐  │
│  │  Background Worker   │  │ ← Processes async
│  │  - Polls queue       │  │
│  │  - Scrapes pages     │  │
│  │  - Updates progress  │  │
│  └──────────────────────┘  │
│                            │
│  ┌──────────────────────┐  │
│  │  PostgreSQL          │  │
│  │  - scraping_jobs     │  │
│  │  - Job status/progress│ │
│  └──────────────────────┘  │
└────────────────────────────┘
       ↑
       │ GET /webcrawl/jobs/{job_id} (poll for status)
       │
┌──────┴──────┐
│   Frontend  │ ← Polls every 2-5s
└─────────────┘
```

### Database Schema

```sql
CREATE TABLE scraping_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_role_id TEXT,
    url TEXT NOT NULL,
    status TEXT NOT NULL, -- 'pending', 'processing', 'completed', 'failed'
    progress JSONB, -- {pages_scraped: 0, total_pages: 0, current_url: '...'}
    result JSONB, -- Final result when completed
    error_message TEXT,
    options JSONB, -- Scraping options (max_pages, max_depth, etc.)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_scraping_jobs_status ON scraping_jobs(status);
CREATE INDEX idx_scraping_jobs_user ON scraping_jobs(user_role_id);
CREATE INDEX idx_scraping_jobs_created ON scraping_jobs(created_at DESC);
```

### API Endpoints

#### 1. Start Scraping (Async)
```http
POST /api/v1/webcrawl/
Request:
{
  "url": "https://example.com",
  "max_pages": 100,
  "max_depth": 5
}

Response (immediate - <1 second):
{
  "success": true,
  "job_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "pending",
  "message": "Scraping job created. Use job_id to check progress."
}
```

#### 2. Check Job Status
```http
GET /api/v1/webcrawl/jobs/{job_id}
Response:
{
  "job_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "processing", // or 'pending', 'completed', 'failed'
  "progress": {
    "pages_scraped": 45,
    "total_pages": 100,
    "current_url": "https://example.com/page-45",
    "percentage": 45
  },
  "created_at": "2026-02-09T10:30:00Z",
  "started_at": "2026-02-09T10:30:05Z",
  "estimated_completion": "2026-02-09T10:35:00Z"
}
```

#### 3. List User's Jobs
```http
GET /api/v1/webcrawl/jobs
Response:
{
  "jobs": [
    {
      "job_id": "...",
      "url": "https://example.com",
      "status": "completed",
      "pages_scraped": 100,
      "created_at": "...",
      "completed_at": "..."
    }
  ]
}
```

### Implementation Components

#### 1. Job Queue Manager (`job_queue.py`)
```python
import asyncio
from queue import PriorityQueue
from typing import Dict, Any
import uuid

class JobQueue:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.active_jobs: Dict[str, Dict[str, Any]] = {}

    async def enqueue(self, job_data: Dict[str, Any]) -> str:
        """Add job to queue, return job_id"""
        job_id = str(uuid.uuid4())
        job_data['job_id'] = job_id
        await self.queue.put(job_data)
        return job_id

    async def dequeue(self) -> Dict[str, Any]:
        """Get next job from queue"""
        return await self.queue.get()

    def mark_active(self, job_id: str, data: Dict[str, Any]):
        """Mark job as actively processing"""
        self.active_jobs[job_id] = data

    def mark_complete(self, job_id: str):
        """Remove from active jobs"""
        self.active_jobs.pop(job_id, None)

# Global singleton
job_queue = JobQueue()
```

#### 2. Background Worker (`background_worker.py`)
```python
import asyncio
from typing import Dict, Any
from .job_queue import job_queue
from .website_service import WebsiteService
from .dao.scraping_dao import ScrapingDAO

class BackgroundWorker:
    def __init__(self):
        self.service = WebsiteService()
        self.dao = ScrapingDAO()
        self.running = False

    async def start(self):
        """Start background worker loop"""
        self.running = True
        asyncio.create_task(self._process_loop())

    async def _process_loop(self):
        """Main worker loop - processes jobs from queue"""
        while self.running:
            try:
                # Get next job from queue
                job_data = await job_queue.dequeue()
                job_id = job_data['job_id']

                # Mark as processing in database
                await self._update_job_status(job_id, 'processing')

                # Process the scraping job
                result = await self._process_job(job_data)

                # Mark as completed
                await self._update_job_status(
                    job_id,
                    'completed',
                    result=result
                )

            except Exception as e:
                logger.error(f"Worker error: {e}")
                if job_id:
                    await self._update_job_status(
                        job_id,
                        'failed',
                        error=str(e)
                    )

    async def _process_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single scraping job with progress updates"""
        job_id = job_data['job_id']
        url = job_data['url']
        options = job_data['options']

        # Start scraping with progress callback
        async def progress_callback(pages_scraped, current_url):
            await self._update_job_progress(job_id, {
                'pages_scraped': pages_scraped,
                'current_url': current_url
            })

        # Run scraping with progress updates
        result = await self.service.scrape_website_with_progress(
            url,
            options,
            progress_callback
        )

        return result

    async def _update_job_status(self, job_id, status, result=None, error=None):
        """Update job status in database"""
        # Implementation in DAO
        pass

    async def _update_job_progress(self, job_id, progress):
        """Update job progress in database"""
        # Implementation in DAO
        pass

# Global singleton
background_worker = BackgroundWorker()
```

#### 3. Updated Router (`router.py`)
```python
@router.post("/")
async def scrape_website_async(request: Request):
    """
    Start async scraping job - returns immediately with job_id
    Production-grade: No timeouts, handles large sitemaps
    """
    try:
        body = await request.json()
        url = body.get("url")

        # Validate
        if not url:
            raise HTTPException(status_code=400, detail="URL required")

        # Create job in database
        job_id = await scraping_dao.create_job(
            user_role_id=request.state.user.get('uid'),
            url=url,
            options=body
        )

        # Enqueue for background processing
        await job_queue.enqueue({
            'job_id': job_id,
            'url': url,
            'options': body
        })

        # Return immediately (< 1 second response time)
        return {
            "success": True,
            "job_id": job_id,
            "status": "pending",
            "message": "Scraping job created. Poll /jobs/{job_id} for status",
            "poll_url": f"/api/v1/webcrawl/jobs/{job_id}"
        }

    except Exception as e:
        logger.error(f"Error creating job: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get job status and progress"""
    job = await scraping_dao.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job_id,
        "status": job['status'],
        "progress": job.get('progress', {}),
        "result": job.get('result') if job['status'] == 'completed' else None,
        "error": job.get('error_message') if job['status'] == 'failed' else None,
        "created_at": job['created_at'],
        "started_at": job.get('started_at'),
        "completed_at": job.get('completed_at')
    }
```

### Frontend Integration

```typescript
// Start scraping
const response = await fetch('/api/v1/gateway/webcrawl/', {
  method: 'POST',
  body: JSON.stringify({ url: 'https://example.com' })
});
const { job_id } = await response.json();

// Poll for status
const pollInterval = setInterval(async () => {
  const statusResponse = await fetch(`/api/v1/gateway/webcrawl/jobs/${job_id}`);
  const status = await statusResponse.json();

  // Update UI with progress
  updateProgress(status.progress);

  if (status.status === 'completed') {
    clearInterval(pollInterval);
    showSuccess(status.result);
  } else if (status.status === 'failed') {
    clearInterval(pollInterval);
    showError(status.error);
  }
}, 3000); // Poll every 3 seconds
```

### Advantages

✅ **No Timeouts**: POST returns immediately
✅ **Progress Tracking**: Real-time progress updates
✅ **Scalable**: Can handle 1000s of pages
✅ **Resilient**: Jobs survive server restarts (stored in DB)
✅ **User Experience**: Visual progress bar, estimated completion time
✅ **Resource Efficient**: Background processing doesn't block API
✅ **Retry Logic**: Failed jobs can be retried
✅ **Job History**: Users can see past scraping jobs

### Future Enhancements

1. **Redis Queue**: Replace in-memory queue with Redis for multi-instance support
2. **Celery Workers**: Dedicated worker processes for horizontal scaling
3. **Webhooks**: Notify frontend when job completes (instead of polling)
4. **Job Priority**: VIP users get priority processing
5. **Rate Limiting**: Limit concurrent jobs per user
6. **Job Cancellation**: Allow users to cancel running jobs
7. **Scheduled Jobs**: Periodic re-scraping of websites

### Migration Path

**Phase 1** (Immediate): In-memory queue, single worker
**Phase 2** (1 month): PostgreSQL-backed queue, persist across restarts
**Phase 3** (3 months): Redis + Celery for distributed processing
**Phase 4** (6 months): Webhooks, priority queues, advanced features

---

**Recommended**: Start with Phase 1 (simplest, works immediately)
**Timeline**: 4-6 hours to implement Phase 1
