# Child Page Deletion - Complete Guide

## ✅ Status: FULLY IMPLEMENTED & SAFE

Individual child pages can be safely deleted **without affecting siblings or parents**.

---

## How It Works

### Detection Logic

When you delete a page, the system **automatically detects** whether it's a parent or child:

```python
# In comprehensive_deletion_service.py
website_record = await conn.fetchrow(
    "SELECT ... parent_id FROM scraped_websites WHERE id = $1",
    website_id
)

is_parent = website_record['parent_id'] is None
# If parent_id is NULL → This is a PARENT
# If parent_id is NOT NULL → This is a CHILD
```

### Deletion Flow

#### **Scenario 1: Delete a CHILD page**

```
Website Structure:
├─ Parent Website (ID: 100)
├─ Child Page 1 (ID: 101) ← DELETE THIS
├─ Child Page 2 (ID: 102)
└─ Child Page 3 (ID: 103)

Steps:
1. System detects: is_parent = False (parent_id=100)
2. Fetch child pages: None (skip for child pages)
3. Delete ONLY page 101
4. Parent (100) UNTOUCHED ✅
5. Siblings (102, 103) UNTOUCHED ✅

Result: Only page 101 deleted, others unaffected
```

#### **Scenario 2: Delete a PARENT website**

```
Website Structure:
├─ Parent Website (ID: 100) ← DELETE THIS
├─ Child Page 1 (ID: 101)
├─ Child Page 2 (ID: 102)
└─ Child Page 3 (ID: 103)

Steps:
1. System detects: is_parent = True (parent_id=NULL)
2. Fetch child pages: [101, 102, 103]
3. Delete parent 100 + all children 101, 102, 103 (atomic)
4. ALL pages deleted together

Result: Entire tree deleted atomically
```

---

## Code Implementation

### Detection Phase (Lines 742-764)

```python
# Get website record
website_record = await conn.fetchrow(
    "SELECT id, original_url, parent_id, ... FROM scraped_websites WHERE id = $1 FOR UPDATE",
    website_id
)

is_parent = website_record['parent_id'] is None  # True if parent, False if child
deletion_report["is_parent"] = is_parent

logger.info(f"✅ [LOOKUP] Found: {website_record['original_url']}")
logger.info(f"   Type: {'Parent Website' if is_parent else 'Child Page'}")

# IMPORTANT: Only fetch children if this is a PARENT
child_pages = []
if is_parent:  # Only if parent_id is NULL
    logger.info(f"📍 [LOOKUP_CHILDREN] Fetching child pages...")
    child_pages = await conn.fetch(
        "SELECT id, original_url, ... FROM scraped_websites WHERE parent_id = $1 FOR UPDATE",
        website_id
    )
    logger.info(f"   Found {len(child_pages)} child pages")
```

**Key Point**: `child_pages` is only populated if `is_parent=True`
- If deleting a child: `child_pages` = [] (empty)
- If deleting a parent: `child_pages` = [all children]

### Deletion Phase (Lines 933-952)

```python
# Build all_pages list
all_pages = [website_record] + child_pages  # Parent + children (or just child)

# ATOMIC transaction - all or nothing
async with conn.transaction():
    # Soft delete version
    if not hard_delete:
        # Mark this page as deleted
        await conn.execute(
            "UPDATE scraped_websites SET processing_status = 'deleted' WHERE id = $1",
            website_id
        )

        # Mark child pages as deleted (only if this is a parent with children)
        if child_pages:
            await conn.execute(
                "UPDATE scraped_websites SET processing_status = 'deleted' WHERE parent_id = $1",
                website_id
            )
```

**Atomic Safety**: All deletions happen together in one transaction
- If deleting a child: Only 1 record updated
- If deleting a parent: Parent + all children updated together
- If error occurs: All changes rolled back (all-or-nothing)

---

## Example Scenarios

### Scenario A: Delete Child Page 2 (Keep siblings)

**Database Before**:
```
ID  | URL              | Parent_ID | Status
----|------------------|-----------|----------
100 | example.com      | NULL      | completed
101 | example.com/page1| 100       | completed
102 | example.com/page2| 100       | completed  ← DELETE THIS
103 | example.com/page3| 100       | completed
```

**API Call**:
```bash
DELETE /api/v1/knowledgebase/web/102
```

**System Detection**:
```
1. SELECT parent_id FROM scraped_websites WHERE id = 102
   → Returns: 100 (NOT NULL)
   → is_parent = False
   → This is a CHILD PAGE ✅

2. Skip child page fetch (is_parent = False)
   → child_pages = []

3. all_pages = [page_102 record]
```

**Deletion**:
```sql
UPDATE scraped_websites SET processing_status = 'deleted' WHERE id = 102
-- Only page 102 updated

-- Note: No "WHERE parent_id = 102" clause because child_pages is empty
```

**Database After**:
```
ID  | URL              | Parent_ID | Status
----|------------------|-----------|----------
100 | example.com      | NULL      | completed  ✅ UNCHANGED
101 | example.com/page1| 100       | completed  ✅ UNCHANGED
102 | example.com/page2| 100       | deleted    ❌ DELETED
103 | example.com/page3| 100       | completed  ✅ UNCHANGED
```

**Response**:
```json
{
  "success": true,
  "item_id": "102",
  "item_type": "website",
  "url": "example.com/page2",
  "is_parent": false,              // ← Shows this was a child page
  "child_pages_count": 0,          // ← No children affected
  "cleanup_summary": {
    "celery_tasks_revoked": 1,     // Only this page's task
    "db_records_affected": 1       // Only this page's record
  }
}
```

---

### Scenario B: Delete Parent Website (Delete all children too)

**Database Before**:
```
ID  | URL              | Parent_ID | Status
----|------------------|-----------|----------
100 | example.com      | NULL      | completed  ← DELETE THIS
101 | example.com/page1| 100       | completed
102 | example.com/page2| 100       | completed
103 | example.com/page3| 100       | completed
```

**API Call**:
```bash
DELETE /api/v1/knowledgebase/web/100
```

**System Detection**:
```
1. SELECT parent_id FROM scraped_websites WHERE id = 100
   → Returns: NULL
   → is_parent = True
   → This is a PARENT WEBSITE ✅

2. Fetch all children:
   SELECT id FROM scraped_websites WHERE parent_id = 100
   → Returns: [101, 102, 103]
   → child_pages = [page_101, page_102, page_103]

3. all_pages = [page_100, page_101, page_102, page_103]
```

**Deletion** (Atomic Transaction):
```sql
UPDATE scraped_websites SET processing_status = 'deleted' WHERE id = 100
-- Parent page deleted

UPDATE scraped_websites SET processing_status = 'deleted' WHERE parent_id = 100
-- All children deleted together
-- This updates pages: 101, 102, 103
```

**Database After**:
```
ID  | URL              | Parent_ID | Status
----|------------------|-----------|----------
100 | example.com      | NULL      | deleted    ❌ DELETED
101 | example.com/page1| 100       | deleted    ❌ DELETED
102 | example.com/page2| 100       | deleted    ❌ DELETED
103 | example.com/page3| 100       | deleted    ❌ DELETED
```

**Response**:
```json
{
  "success": true,
  "item_id": "100",
  "item_type": "website",
  "url": "example.com",
  "is_parent": true,               // ← Shows this was a parent
  "child_pages_count": 3,          // ← 3 children were also deleted
  "cleanup_summary": {
    "celery_tasks_revoked": 4,     // Parent + 3 children tasks
    "db_records_affected": 4       // Parent + 3 children records
  }
}
```

---

## Safety Guarantees

### ✅ Isolation
- Deleting a child: **Only affects that child**, siblings untouched
- Deleting a parent: **Affects parent + children**, siblings unaffected

### ✅ Atomicity
- All deletions in transaction: All-or-nothing
- If error occurs: Everything rolled back
- No partial deletes possible

### ✅ Consistency
- Parent-child relationships maintained
- No orphaned pages (if parent deleted, children must be too)
- No "lost" pages

### ✅ Row-Level Locking
- `FOR UPDATE` on initial SELECT
- Prevents concurrent modifications
- Thread-safe deletion

---

## Verification - How to Test

### Test 1: Delete Child, Verify Parent Unchanged

```sql
-- Before deletion
SELECT id, parent_id, processing_status
FROM scraped_websites
WHERE parent_id = 100
ORDER BY id;

-- Result:
-- 101, 100, completed
-- 102, 100, completed
-- 103, 100, completed

-- DELETE child 102
-- curl -X DELETE "http://localhost:8000/api/v1/knowledgebase/web/102"

-- After deletion
SELECT id, parent_id, processing_status
FROM scraped_websites
WHERE parent_id = 100
ORDER BY id;

-- Result:
-- 101, 100, completed  ✅ UNCHANGED
-- 102, 100, deleted    ❌ DELETED
-- 103, 100, completed  ✅ UNCHANGED

-- Parent still active:
SELECT id, processing_status FROM scraped_websites WHERE id = 100;
-- Result: 100, completed  ✅ PARENT UNCHANGED
```

### Test 2: Delete Parent, Verify All Children Deleted

```sql
-- Before deletion
SELECT COUNT(*) FROM scraped_websites WHERE parent_id = 100 AND processing_status = 'completed';
-- Result: 3 children active

-- DELETE parent 100
-- curl -X DELETE "http://localhost:8000/api/v1/knowledgebase/web/100"

-- After deletion
SELECT COUNT(*) FROM scraped_websites WHERE parent_id = 100 AND processing_status = 'deleted';
-- Result: 3 children deleted  ✅

SELECT processing_status FROM scraped_websites WHERE id = 100;
-- Result: deleted  ✅ PARENT DELETED TOO
```

### Test 3: Verify Response Shows Correct Info

```bash
# Delete a child page
curl -X DELETE "http://localhost:8000/api/v1/knowledgebase/web/102" | jq .

# Check response:
# {
#   "is_parent": false,          ← Shows it was a child
#   "child_pages_count": 0,      ← No children affected
#   "cleanup_summary": {
#     "db_records_affected": 1   ← Only 1 record (itself)
#   }
# }

# Delete a parent website
curl -X DELETE "http://localhost:8000/api/v1/knowledgebase/web/100" | jq .

# Check response:
# {
#   "is_parent": true,           ← Shows it was a parent
#   "child_pages_count": 3,      ← 3 children affected
#   "cleanup_summary": {
#     "db_records_affected": 4   ← Parent + 3 children
#   }
# }
```

---

## API Response Interpretation

### For Child Page Deletion
```json
{
  "is_parent": false,
  "child_pages_count": 0,
  "cleanup_summary": {
    "db_records_affected": 1,
    "celery_tasks_revoked": 1
  }
}
// Interpretation: Only 1 page deleted, siblings safe
```

### For Parent Website Deletion
```json
{
  "is_parent": true,
  "child_pages_count": 5,
  "cleanup_summary": {
    "db_records_affected": 6,      // Parent + 5 children
    "celery_tasks_revoked": 6      // Parent + 5 children tasks
  }
}
// Interpretation: Parent + 5 children deleted together (atomic)
```

---

## Database Queries to Check Page Type

### Check if a page is a parent
```sql
SELECT id, original_url, parent_id
FROM scraped_websites
WHERE id = ?
AND parent_id IS NULL;
-- Returns: Parent website (no parent_id)
```

### Check if a page is a child
```sql
SELECT id, original_url, parent_id
FROM scraped_websites
WHERE id = ?
AND parent_id IS NOT NULL;
-- Returns: Child page (has parent_id)
```

### Get all children of a parent
```sql
SELECT id, original_url, parent_id
FROM scraped_websites
WHERE parent_id = ?;
-- Returns: All child pages
```

### Get siblings of a page
```sql
SELECT id, original_url
FROM scraped_websites
WHERE parent_id = (
  SELECT parent_id FROM scraped_websites WHERE id = ?
)
AND id != ?;
-- Returns: All sibling pages (excluding self)
```

---

## Summary

✅ **Individual child pages are safely deletable**
- System auto-detects parent vs child
- Deleting child: Only affects that child
- Deleting parent: Deletes parent + all children (atomic)
- Siblings always safe (unaffected by child deletion)
- Atomic transactions guarantee consistency
- Row-level locking prevents race conditions

**Implementation**: Fully in `comprehensive_deletion_service.py`
**Status**: Production-ready and safe
**No additional code needed** - just use the existing deletion endpoints!
