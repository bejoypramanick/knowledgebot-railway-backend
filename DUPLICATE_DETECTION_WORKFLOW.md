# Duplicate Detection - Frontend Workflow

## 🎯 Overview

When a user tries to upload a duplicate file or crawl a duplicate website, the system:
1. Detects the duplicate → Returns 409 Conflict with details
2. Shows alert to user asking if they want to override
3. If user confirms → Calls DELETE endpoint first, then uploads new content
4. Shows success/failure

This explicit, two-step override process gives users full control and visibility.

---

## 📋 User Workflow

### File Upload Flow

```
┌─────────────────────────────────────────────────────┐
│ User selects file and clicks Upload                 │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│ Frontend calls:                                     │
│ POST /api/v1/knowledgebase/files/upload/async      │
│ (WITHOUT replace_existing)                          │
└─────────────────────────────────────────────────────┘
                       ↓
      ┌────────────────┴────────────────┐
      │                                 │
   ✅ NEW FILE                    ❌ DUPLICATE (409)
      │                                 │
      ↓                                 ↓
  Upload succeeds            ┌──────────────────────┐
  Show success               │ SHOW ALERT TO USER:  │
                             │                      │
                             │ "This file already   │
                             │  exists:             │
                             │  Name: document.pdf  │
                             │  Hash: a1b2c3...     │
                             │                      │
                             │ [Cancel] [Override]  │
                             └──────────────────────┘
                                       │
                     ┌─────────────────┴─────────────────┐
                     │                                   │
                  CANCEL                            OVERRIDE
                     │                                   │
              Stop upload                                ↓
                                        ┌─────────────────────────┐
                                        │ Step 1: DELETE OLD FILE │
                                        │                         │
                                        │ Call:                   │
                                        │ DELETE /files/{file_id} │
                                        │ (from response)         │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Show: "Removing old     │
                                        │ version..."             │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Wait for deletion       │
                                        │ to complete (DELETE     │
                                        │ endpoint returns 200)   │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Step 2: UPLOAD NEW FILE │
                                        │                         │
                                        │ Call:                   │
                                        │ POST /files/upload/     │
                                        │ async (new file)        │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Show success:           │
                                        │ "File uploaded!"        │
                                        │ New ID: 456             │
                                        └─────────────────────────┘
```

### Website Crawl Flow

```
┌─────────────────────────────────────────────────────┐
│ User enters URL and clicks Crawl                     │
└─────────────────────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────┐
│ Frontend calls:                                     │
│ POST /api/v1/knowledgebase/webcrawl                │
│ (WITHOUT replace_existing)                          │
└─────────────────────────────────────────────────────┘
                       ↓
      ┌────────────────┴────────────────┐
      │                                 │
   ✅ NEW WEBSITE                ❌ DUPLICATE (409)
      │                                 │
      ↓                                 ↓
  Crawl starts               ┌──────────────────────┐
  Show progress              │ SHOW ALERT TO USER:  │
                             │                      │
                             │ "This website is     │
                             │  already crawled:    │
                             │  URL: example.com    │
                             │  Status: completed   │
                             │                      │
                             │ [Cancel] [Override]  │
                             └──────────────────────┘
                                       │
                     ┌─────────────────┴─────────────────┐
                     │                                   │
                  CANCEL                            OVERRIDE
                     │                                   │
              Stop (don't crawl)                         ↓
                                        ┌─────────────────────────┐
                                        │ Step 1: DELETE OLD      │
                                        │ WEBSITE                 │
                                        │                         │
                                        │ Call:                   │
                                        │ DELETE /web/{website_id}│
                                        │ (from response)         │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Show: "Removing old     │
                                        │ crawl..."               │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Wait for deletion       │
                                        │ to complete (DELETE     │
                                        │ endpoint returns 200)   │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Step 2: CRAWL NEW       │
                                        │ WEBSITE                 │
                                        │                         │
                                        │ Call:                   │
                                        │ POST /webcrawl          │
                                        │ (same URL)              │
                                        └─────────────────────────┘
                                                   ↓
                                        ┌─────────────────────────┐
                                        │ Show crawling progress: │
                                        │ "Crawling: 5/23 pages"  │
                                        └─────────────────────────┘
```

---

## 🔌 API Endpoints Used

### File Upload

**Step 0: Detect Duplicate** (Always call first, without replace_existing)
```bash
POST /api/v1/knowledgebase/files/upload/async
Content-Type: multipart/form-data

file=<file_content>
file_display_name=<optional>
replace_existing=false  (or omit - defaults to false)
```

**Response if Duplicate (409 Conflict):**
```json
{
  "success": false,
  "error": "Duplicate file detected",
  "match_type": "hash",
  "existing_file_id": "123",
  "existing_file_name": "document_v1.pdf",
  "existing_file_hash": "a1b2c3d4e5f6..."
}
```

**Step 1: Delete Existing (If User Confirms Override)**
```bash
DELETE /api/v1/knowledgebase/files/123?hard_delete=false

# Response: 200 OK
{
  "success": true,
  "item_id": "123",
  "message": "File deleted successfully"
}
```

**Step 2: Upload New File (After Deletion Completes)**
```bash
POST /api/v1/knowledgebase/files/upload/async
Content-Type: multipart/form-data

file=<file_content>
file_display_name=<optional>
replace_existing=false  (or omit)
```

**Response if New Upload Succeeds (200 OK):**
```json
{
  "success": true,
  "file_id": "456",
  "status": "pending",
  "message": "File uploaded successfully and queued for processing"
}
```

---

### Website Crawl

**Step 0: Detect Duplicate** (Always call first, without replace_existing)
```bash
POST /api/v1/knowledgebase/webcrawl
Content-Type: application/json

{
  "url": "https://example.com",
  "max_depth": 2,
  "max_pages": 100,
  "request_per_second": 5,
  "replace_existing": false  (or omit - defaults to false)
}
```

**Response if Duplicate (409 Conflict):**
```json
{
  "success": false,
  "error": "Website is already being crawled or has been crawled",
  "duplicate_website_id": "123",
  "duplicate_url": "https://example.com",
  "duplicate_status": "completed"
}
```

**Step 1: Delete Existing Website (If User Confirms Override)**
```bash
DELETE /api/v1/knowledgebase/web/123?hard_delete=false

# Response: 200 OK
{
  "success": true,
  "item_id": "123",
  "is_parent": true,
  "child_pages_count": 5,
  "message": "Website and child pages deleted successfully"
}
```

**Step 2: Crawl New Website (After Deletion Completes)**
```bash
POST /api/v1/knowledgebase/webcrawl
Content-Type: application/json

{
  "url": "https://example.com",
  "max_depth": 2,
  "max_pages": 100,
  "request_per_second": 5,
  "replace_existing": false  (or omit)
}
```

**Response if New Crawl Succeeds (200 OK):**
```json
{
  "success": true,
  "website_id": "456",
  "status": "queued",
  "message": "Website queued for scraping"
}
```

---

## 📝 Frontend Implementation Notes

### Alert Modal Content

**File Upload Alert:**
```
Title: "File Already Exists"

Message:
"This file already exists in your knowledge base:

Name: document_v1.pdf
Size: 2.4 MB
Hash: a1b2c3d4e5f6...

Do you want to replace it with the new version?"

Buttons: [Cancel] [Replace]
```

**Website Crawl Alert:**
```
Title: "Website Already Crawled"

Message:
"This website is already in your knowledge base:

URL: https://example.com
Status: completed
Pages: 23

Do you want to re-crawl it with updated settings?"

Buttons: [Cancel] [Re-crawl]
```

### State Management

**During Override Process:**

```typescript
// State to track override process
const [overrideInProgress, setOverrideInProgress] = useState(false);
const [deleteInProgress, setDeleteInProgress] = useState(false);
const [deleteError, setDeleteError] = useState(null);

// On user confirms override
async function handleOverrideConfirm(duplicateId, fileOrUrl) {
  try {
    setOverrideInProgress(true);

    // Step 1: Delete
    setDeleteInProgress(true);
    const deleteResponse = await fetch(
      `/api/v1/knowledgebase/${isFile ? 'files' : 'web'}/${duplicateId}`,
      { method: 'DELETE' }
    );

    if (!deleteResponse.ok) {
      setDeleteError(`Failed to delete: ${deleteResponse.statusText}`);
      setDeleteInProgress(false);
      return;
    }

    setDeleteInProgress(false);

    // Step 2: Upload/Crawl new content
    // Re-submit the original upload/crawl request
    await submitNewUploadOrCrawl();

  } catch (error) {
    setDeleteError(error.message);
  } finally {
    setOverrideInProgress(false);
  }
}
```

### Error Handling

**If Delete Fails:**
- Show error: "Could not remove the existing file. Please try again."
- Offer options:
  - Retry delete
  - Cancel override
  - Contact support

**If Upload/Crawl Fails After Delete:**
- The old file/website is already deleted (soft delete)
- Show error: "Failed to upload new file. You can retry uploading."
- User must retry the upload

---

## 🛡️ Safety Guarantees

✅ **Two-Step Override = Safety**
1. Delete happens first (soft delete - reversible)
2. Upload happens second (only after delete succeeds)
3. User sees progress at each step

✅ **No Data Loss**
- Soft delete only (old file marked as deleted, not removed)
- If new upload fails, user can retry
- Audit trail preserved

✅ **User Control**
- User explicitly confirms before deletion
- User sees what's being replaced
- Clear alerts at each step

---

## 📊 Example User Interactions

### Scenario 1: User Wants to Upload Updated Document

```
User: "I have an updated version of document.pdf"
Frontend: Attempts upload
Backend: Returns 409 "Duplicate detected: a1b2c3d4..."
Frontend: Shows alert with old file details
User: Clicks [Replace]
Frontend: Calls DELETE /files/123
Backend: Soft deletes file (status='deleted')
Frontend: Calls POST /upload with new document.pdf
Backend: Uploads new file (ID: 456)
Frontend: Shows "Document updated! (New version will be processed)"
```

### Scenario 2: User Wants to Re-crawl Website

```
User: "I want to re-crawl example.com with more pages"
Frontend: Attempts crawl with max_pages=1000
Backend: Returns 409 "Website already crawled"
Frontend: Shows alert with current crawl status
User: Clicks [Re-crawl]
Frontend: Calls DELETE /web/100
Backend: Soft deletes website and 23 child pages
Frontend: Calls POST /webcrawl with new settings
Backend: Starts new crawl (ID: 200)
Frontend: Shows "Re-crawling in progress... 0/? pages"
```

### Scenario 3: User Changes Mind

```
User: Starts uploading duplicate file
Frontend: Shows alert with override option
User: Clicks [Cancel]
Frontend: Dismisses alert, upload cancelled
Backend: No deletion happens
Result: Original file stays in knowledge base
```

---

## ✅ Implementation Checklist

- [ ] Frontend: Show modal/alert when 409 received
- [ ] Frontend: Extract duplicate_id from 409 response
- [ ] Frontend: Add [Cancel] and [Override] buttons to alert
- [ ] Frontend: Call DELETE endpoint with duplicate_id
- [ ] Frontend: Show "Removing old..." progress indicator
- [ ] Frontend: Wait for DELETE to return 200 OK
- [ ] Frontend: Then call POST upload/crawl endpoint
- [ ] Frontend: Show upload/crawl progress as normal
- [ ] Backend: Already returns 409 with duplicate info ✅
- [ ] Backend: Already supports soft delete ✅

---

## Summary

**Override Flow:**
1. Detect duplicate → 409 Conflict with details
2. Show alert to user with file/URL info
3. User confirms → Call DELETE endpoint first
4. Wait for deletion → Call upload/crawl endpoint
5. Show success

This explicit two-step process:
- ✅ Gives user full control
- ✅ Provides visibility at each step
- ✅ Is reversible (soft delete)
- ✅ Prevents accidental overwrites
- ✅ Creates clear audit trail
