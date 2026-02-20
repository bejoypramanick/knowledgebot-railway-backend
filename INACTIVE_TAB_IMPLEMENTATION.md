# Inactive Tab Implementation

## Overview
Added support for filtering items by status to enable the "Not Active" tab in the frontend UI.

## Backend Changes

### API Endpoint: `/api/v1/gateway/knowledgebase/files`

**New Query Parameter:**
- `status` (optional): Filter items by status
  - `status=inactive`: Returns only items with status "cancelled", "deleted", or "failed"
  - No status parameter (default): Returns only active items (excludes cancelled/deleted/failed)

**Response Format:**
```json
{
  "success": true,
  "files": [...],
  "websites": [...],
  "count": 10,
  "sources": {
    "upload": 5,
    "scrape": 5
  }
}
```

### Filtering Logic

**Inactive Statuses:**
- `cancelled` - Task was cancelled by user
- `deleted` - Item was deleted
- `failed` - Processing failed with error

**Active Statuses:**
- `completed` - Successfully processed
- `processing` - Currently being processed
- `pending` - Queued for processing
- `queued` - In queue waiting to start

### Implementation Details

**File:** `knowledgebase_ingestion/routers/fileupload_router.py`

```python
@router.get("/files")
async def get_all_files(request: Request = None, status: Optional[str] = None):
    """
    Get all files and websites with their current status
    
    Query Parameters:
        status: Optional filter for item status
            - 'inactive': Returns only cancelled, deleted, or failed items
            - None (default): Returns all active items
    """
    # ... implementation
```

**Filtering:**
1. Fetches all files and websites from database
2. Filters based on `processing_status` field
3. Returns filtered results with hierarchical structure maintained

## Frontend Integration

The frontend automatically uses this endpoint:
- **Active Tab**: Calls `/files` (no status param) - shows active items
- **Not Active Tab**: Calls `/files?status=inactive` - shows inactive items

**Fallback:** If backend endpoint is not available, frontend filters locally from all loaded items.

## Testing

**Test Active Items:**
```bash
curl -H "Authorization: Bearer <token>" \
  "https://api.example.com/api/v1/gateway/knowledgebase/files"
```

**Test Inactive Items:**
```bash
curl -H "Authorization: Bearer <token>" \
  "https://api.example.com/api/v1/gateway/knowledgebase/files?status=inactive"
```

## Database Schema

No database changes required. Uses existing `processing_status` column in:
- `uploaded_files` table
- `scraped_websites` table

## Notes

- Maintains hierarchical structure for websites in both active and inactive views
- Filtering is case-insensitive
- Both files and websites are filtered consistently
- Excel export uses proper source labels (File/Web)
