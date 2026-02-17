# Simple Refresh Button for Task Status

Simple approach: User clicks "Refresh" button → Fetches latest status → Updates tree

---

## Backend Endpoints (Already Exist)

### Get Processing Status
```
GET /api/v1/knowledgebase/status
```

Returns:
```json
{
  "success": true,
  "files": [
    {
      "id": "123",
      "type": "file",
      "name": "document.pdf",
      "processing_status": "processing",
      "error_message": null,
      "created_at": "2026-02-17T18:00:00Z",
      "updated_at": "2026-02-17T18:05:00Z"
    }
  ],
  "websites": [
    {
      "id": "456",
      "type": "website",
      "name": "https://example.com/sitemap.xml",
      "processing_status": "pending",
      "error_message": null,
      "created_at": "2026-02-17T18:00:00Z",
      "updated_at": "2026-02-17T18:00:00Z"
    }
  ]
}
```

### Get Single Item Status
```
GET /api/v1/knowledgebase/status/{item_id}
```

### Cancel Task
```
POST /api/v1/knowledgebase/cancel/{item_id}
POST /api/v1/knowledgebase/cancel-all
```

---

## Frontend Implementation

### Simple Hook: `useStatusRefresh.tsx`

```typescript
import { useState } from 'react';

interface ProcessingItem {
  id: string;
  type: 'file' | 'website';
  name: string;
  processing_status: 'pending' | 'processing' | 'completed' | 'cancelled' | 'failed';
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

interface StatusResponse {
  success: boolean;
  files: ProcessingItem[];
  websites: ProcessingItem[];
}

export function useStatusRefresh(apiBaseUrl: string, getAuthHeaders: () => Promise<any>) {
  const [isLoading, setIsLoading] = useState(false);
  const [processingItems, setProcessingItems] = useState<ProcessingItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshStatus = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${apiBaseUrl}/api/v1/knowledgebase/status`, {
        headers
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch status: ${response.statusText}`);
      }

      const data: StatusResponse = await response.json();

      // Combine files and websites
      const allItems = [
        ...data.files.map(f => ({ ...f, type: 'file' as const })),
        ...data.websites.map(w => ({ ...w, type: 'website' as const }))
      ];

      // Filter to only processing/pending items
      const activeItems = allItems.filter(
        item => item.processing_status === 'pending' || item.processing_status === 'processing'
      );

      setProcessingItems(activeItems);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
      console.error('Error refreshing status:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return {
    processingItems,
    isLoading,
    error,
    refreshStatus
  };
}
```

### Update KnowledgeBaseManagement Component

```typescript
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';
import { useStatusRefresh } from '../hooks/useStatusRefresh';

export default function KnowledgeBaseManagement() {
  const { processingItems, isLoading, refreshStatus } = useStatusRefresh(
    BACKEND_CONFIG.endpoints.apiGateway,
    async () => await this.getAuthHeaders() // Your auth logic
  );

  // Call on component mount
  useEffect(() => {
    refreshStatus();
  }, []);

  const cancelTask = async (itemId: string) => {
    try {
      const response = await fetch(
        `${BACKEND_CONFIG.endpoints.apiGateway}/api/v1/knowledgebase/cancel/${itemId}`,
        {
          method: 'POST',
          headers: await this.getAuthHeaders()
        }
      );

      if (!response.ok) throw new Error('Failed to cancel');

      toast({
        title: 'Task Cancelled',
        description: 'Task has been cancelled. Refresh to see changes.'
      });

      // Refresh status immediately
      await refreshStatus();
    } catch (error) {
      toast({
        title: 'Error',
        description: 'Failed to cancel task',
        variant: 'destructive'
      });
    }
  };

  return (
    <div>
      {/* Processing Items Section */}
      {processingItems.length > 0 && (
        <div className="mb-6 p-4 border rounded-lg bg-blue-50 dark:bg-blue-900/20">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h3 className="font-semibold">Processing ({processingItems.length})</h3>
              <p className="text-xs text-gray-600">
                Tasks will appear here as they process. Click refresh to update.
              </p>
            </div>

            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={refreshStatus}
                disabled={isLoading}
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                Refresh
              </Button>

              {processingItems.length > 0 && (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={async () => {
                    if (confirm('Cancel all pending tasks?')) {
                      try {
                        await fetch(
                          `${BACKEND_CONFIG.endpoints.apiGateway}/api/v1/knowledgebase/cancel-all`,
                          {
                            method: 'POST',
                            headers: await this.getAuthHeaders()
                          }
                        );
                        await refreshStatus();
                        toast({ title: 'All tasks cancelled' });
                      } catch (error) {
                        toast({
                          title: 'Error',
                          description: 'Failed to cancel tasks',
                          variant: 'destructive'
                        });
                      }
                    }
                  }}
                >
                  Cancel All
                </Button>
              )}
            </div>
          </div>

          {/* Processing Items List */}
          <div className="space-y-2">
            {processingItems.map((item) => (
              <ProcessingItemRow
                key={`${item.type}-${item.id}`}
                item={item}
                onCancel={() => cancelTask(item.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Rest of the UI */}
    </div>
  );
}
```

### Processing Item Row Component

```typescript
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Loader2, X } from 'lucide-react';

export function ProcessingItemRow({ item, onCancel }) {
  const isProcessing = item.processing_status === 'processing';
  const isPending = item.processing_status === 'pending';

  return (
    <div className="flex items-center justify-between p-3 bg-white dark:bg-zinc-800 rounded border">
      {/* Item Info */}
      <div className="flex-1">
        <div className="flex items-center gap-2">
          {isProcessing && <Loader2 className="h-4 w-4 animate-spin text-blue-600" />}
          <div>
            <p className="font-medium">
              {item.type === 'file' ? '📄' : '🌐'} {item.name}
            </p>
            <p className="text-xs text-gray-500">
              {new Date(item.updated_at).toLocaleTimeString()}
            </p>
          </div>
        </div>
      </div>

      {/* Status Badge */}
      <Badge
        className={`mx-2 ${
          isProcessing
            ? 'bg-blue-100 text-blue-800 dark:bg-blue-900/30'
            : 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30'
        }`}
      >
        {item.processing_status.toUpperCase()}
      </Badge>

      {/* Cancel Button */}
      <Button
        variant="ghost"
        size="sm"
        onClick={onCancel}
        className="text-red-600 hover:text-red-800 hover:bg-red-50"
      >
        <X className="h-4 w-4" />
      </Button>

      {/* Error Message */}
      {item.error_message && (
        <div className="text-xs text-red-600 ml-2" title={item.error_message}>
          ⚠️ Error
        </div>
      )}
    </div>
  );
}
```

---

## Usage

1. **On Component Mount**
   ```typescript
   useEffect(() => {
     refreshStatus(); // Load initial processing items
   }, []);
   ```

2. **User clicks "Refresh" Button**
   ```
   GET /api/v1/knowledgebase/status
     ↓
   Returns list of pending/processing items
     ↓
   Update UI with latest statuses
   ```

3. **User clicks "Cancel" on Task**
   ```
   POST /api/v1/knowledgebase/cancel/{id}
     ↓
   Task marked as cancelled
     ↓
   User clicks Refresh
     ↓
   Item disappears from processing list
   ```

---

## Benefits

✅ **Simple** - Just an HTTP GET call
✅ **No SSE** - No streaming infrastructure needed
✅ **Manual Control** - User controls when to refresh
✅ **Works Offline** - No persistent connections
✅ **Easy Testing** - Can test with curl
✅ **Low Overhead** - Single HTTP call, not streaming

---

## Testing

```bash
# Get all processing items
curl http://localhost:8000/api/v1/knowledgebase/status

# Cancel a task
curl -X POST http://localhost:8000/api/v1/knowledgebase/cancel/123

# Cancel all
curl -X POST http://localhost:8000/api/v1/knowledgebase/cancel-all
```

---

## That's It!

Just:
1. ✅ Create `useStatusRefresh` hook
2. ✅ Create `ProcessingItemRow` component
3. ✅ Add refresh button to KnowledgeBaseManagement
4. ✅ Show processing items when they exist
5. ✅ User manually clicks refresh as needed

No SSE, no streaming, no complexity. Pure HTTP. 🎉
