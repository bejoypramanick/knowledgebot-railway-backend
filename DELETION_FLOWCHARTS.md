# Deletion Flow Charts - All 6 Scenarios

---

## 1️⃣ Scenario 1: Uploaded File Deletion

```
┌─────────────────────────────────────────────────────────────────────────┐
│                  DELETE UPLOADED FILE (e.g., PDF, DOCX)                │
└─────────────────────────────────────────────────────────────────────────┘

                         User Clicks Delete
                              ↓
                    ┌──────────────────────┐
                    │  API: DELETE /file/ID│
                    └──────────────────────┘
                              ↓
                ┌─────────────────────────────────┐
                │ STEP 1: GET FILE RECORD         │
                │ SELECT * FROM file_uploads      │
                │ WHERE id = ID                   │
                └─────────────────────────────────┘
                              ↓
                ┌─────────────────────────────────┐
                │ STEP 2: REVOKE CELERY TASKS     │
                │ (Stop docling, converting, etc) │
                │ ✗ celery_file_worker task      │
                │ ✗ celery_web_worker task       │
                │ ✗ All subprocess tasks         │
                └─────────────────────────────────┘
                              ↓
                ┌─────────────────────────────────┐
                │ STEP 3: CANCEL REDIS STATE      │
                │ DEL file:processing:{ID}        │
                │ DEL file:status:{ID}            │
                │ DEL celery_task_{UUID}          │
                └─────────────────────────────────┘
                              ↓
                ┌─────────────────────────────────┐
                │ STEP 4: DELETE FROM S3          │
                │ ✗ Raw file (s3_key)             │
                │ ✗ Processed markdown            │
                │ ✗ Temp local files              │
                └─────────────────────────────────┘
                              ↓
                ┌─────────────────────────────────┐
                │ STEP 5: DELETE FROM GEMINI      │
                │ DELETE FileSearch document      │
                │ (via Gemini API)                │
                │ Verify with GET → expect 404   │
                └─────────────────────────────────┘
                              ↓
                ┌─────────────────────────────────┐
                │ STEP 6: DELETE FROM DATABASE    │
                │ ATOMIC TRANSACTION:             │
                │ - Soft delete: UPDATE status    │
                │ - Hard delete: DELETE record    │
                │ - Delete metadata entries       │
                │ - Delete search associations    │
                └─────────────────────────────────┘
                              ↓
                        ┌──────────────┐
                        │  SUCCESS ✅  │
                        │ File removed │
                        │  completely  │
                        └──────────────┘

DATA DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ PostgreSQL:  file_uploads record
✗ Celery:      All tasks for this file
✗ Redis:       State, progress, metadata
✗ S3:          Raw file + processed markdown
✗ Gemini:      FileSearch document
✗ Local:       Temp files (if any)

UNAFFECTED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Other files (independent deletion)
✓ Websites (different tables)
✓ Sitemaps (different tables)
```

---

## 2️⃣ Scenario 2: Website With Child Pages Deletion

```
┌──────────────────────────────────────────────────────────────────────────┐
│              DELETE WEBSITE (Parent) + ALL CHILD PAGES                   │
│              Example: Delete example.com + /page1, /page2, /page3       │
└──────────────────────────────────────────────────────────────────────────┘

                         User Clicks Delete
                         on Parent Website
                              ↓
                   ┌─────────────────────────┐
                   │ API: DELETE /website/ID │
                   │ (Parent ID = NULL)      │
                   └─────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 1: DETECT THIS IS A PARENT                │
        │ SELECT parent_id FROM scraped_websites          │
        │ WHERE id = ID                                   │
        │                                                 │
        │ Result: parent_id = NULL → IS PARENT ✓         │
        └─────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 2: FETCH ALL CHILD PAGES                  │
        │ SELECT id FROM scraped_websites                │
        │ WHERE parent_id = ID                           │
        │                                                 │
        │ Result: [101, 102, 103] (3 children)           │
        └─────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 3: REVOKE ALL CELERY TASKS                │
        │ ✗ Parent crawling task                          │
        │ ✗ Child page 101 crawling task                  │
        │ ✗ Child page 102 crawling task                  │
        │ ✗ Child page 103 crawling task                  │
        │ ✗ All processing subtasks                       │
        └─────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 4: CANCEL REDIS STATE                     │
        │ DEL website:crawling:{ID}                       │
        │ DEL website:crawling:{101}                      │
        │ DEL website:crawling:{102}                      │
        │ DEL website:crawling:{103}                      │
        │ DEL all_related_celery_tasks                    │
        └─────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 5: DELETE FROM S3                          │
        │ (Parent + all children)                         │
        │ ✗ Parent temp HTML                              │
        │ ✗ Parent processed markdown                     │
        │ ✗ Child 101 temp HTML + processed markdown      │
        │ ✗ Child 102 temp HTML + processed markdown      │
        │ ✗ Child 103 temp HTML + processed markdown      │
        └─────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 6: DELETE FROM GEMINI                      │
        │ ✗ Parent FileSearch document                    │
        │ ✗ Child page 101 FileSearch document            │
        │ ✗ Child page 102 FileSearch document            │
        │ ✗ Child page 103 FileSearch document            │
        │ (4 total documents deleted)                     │
        └─────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────────────┐
        │ STEP 7: ATOMIC DATABASE TRANSACTION             │
        │ BEGIN TRANSACTION                               │
        │  ✗ UPDATE parent: status = 'deleted'            │
        │  ✗ UPDATE children: status = 'deleted'          │
        │    (WHERE parent_id = ID)                       │
        │  ✗ Delete all metadata                          │
        │ COMMIT (all-or-nothing)                         │
        └─────────────────────────────────────────────────┘
                              ↓
            ┌──────────────────────────────────┐
            │        SUCCESS ✅               │
            │ Parent + 3 Children removed      │
            │ Total: 4 records deleted         │
            └──────────────────────────────────┘

DATA DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ PostgreSQL:  1 parent + 3 children = 4 records
✗ Celery:      4 crawling tasks + subtasks
✗ Redis:       4 crawling states + metadata
✗ S3:          8 files (temp HTML + markdown × 4 pages)
✗ Gemini:      4 FileSearch documents
✗ Local:       Temp files cleaned

UNAFFECTED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Sibling websites (different parent)
✓ Files (different table)
✓ Sitemaps (different table)

RESPONSE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "success": true,
  "is_parent": true,
  "child_pages_count": 3,
  "cleanup_summary": {
    "db_records_affected": 4,
    "celery_tasks_revoked": 4,
    "s3_files_deleted": 8,
    "gemini_docs_deleted": 4
  }
}
```

---

## 3️⃣ Scenario 3: Child Page of Website Deletion (Keep Parent & Siblings)

```
┌──────────────────────────────────────────────────────────────────────────┐
│           DELETE CHILD PAGE ONLY (Parent & Siblings Untouched)           │
│  Example: Delete example.com/page2 from parent example.com               │
│           KEEP: example.com, example.com/page1, example.com/page3        │
└──────────────────────────────────────────────────────────────────────────┘

                         User Clicks Delete
                        on Child Page (page2)
                              ↓
                  ┌──────────────────────────────┐
                  │ API: DELETE /website/102      │
                  │ (Child of parent ID 100)      │
                  └──────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 1: DETECT THIS IS A CHILD PAGE             │
      │ SELECT parent_id FROM scraped_websites           │
      │ WHERE id = 102                                   │
      │                                                  │
      │ Result: parent_id = 100 → IS CHILD (not NULL) ✓│
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 2: SKIP CHILD FETCH                        │
      │ (Because is_parent = False)                      │
      │                                                  │
      │ child_pages = []  (empty list)                   │
      │ → Only this page will be deleted               │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 3: REVOKE CELERY TASK (CHILD ONLY)         │
      │ ✗ Child page 102 crawling task                   │
      │                                                  │
      │ KEEP:                                            │
      │ ✓ Parent (100) task - UNTOUCHED                  │
      │ ✓ Sibling 101 task - UNTOUCHED                   │
      │ ✓ Sibling 103 task - UNTOUCHED                   │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 4: CANCEL REDIS STATE (CHILD ONLY)         │
      │ DEL website:crawling:102                        │
      │                                                  │
      │ KEEP:                                            │
      │ ✓ Parent (100) state - UNTOUCHED                │
      │ ✓ Sibling 101 state - UNTOUCHED                 │
      │ ✓ Sibling 103 state - UNTOUCHED                 │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 5: DELETE FROM S3 (CHILD ONLY)             │
      │ ✗ Child 102 temp HTML                            │
      │ ✗ Child 102 processed markdown                   │
      │                                                  │
      │ KEEP IN S3:                                      │
      │ ✓ Parent (100) files - UNTOUCHED                │
      │ ✓ Sibling 101 files - UNTOUCHED                 │
      │ ✓ Sibling 103 files - UNTOUCHED                 │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 6: DELETE FROM GEMINI (CHILD ONLY)         │
      │ ✗ Child page 102 FileSearch document             │
      │                                                  │
      │ KEEP IN GEMINI:                                  │
      │ ✓ Parent (100) document - UNTOUCHED             │
      │ ✓ Sibling 101 document - UNTOUCHED              │
      │ ✓ Sibling 103 document - UNTOUCHED              │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 7: DATABASE DELETE (CHILD ONLY)            │
      │ BEGIN TRANSACTION                                │
      │  ✗ UPDATE scraped_websites                       │
      │    SET status = 'deleted'                        │
      │    WHERE id = 102                                │
      │  (Note: NO "WHERE parent_id = 102" clause       │
      │   because child_pages is empty)                 │
      │ COMMIT                                           │
      └──────────────────────────────────────────────────┘
                              ↓
        ┌───────────────────────────────────────┐
        │       SUCCESS ✅                      │
        │ Child page 102 deleted ONLY           │
        │ Parent + Siblings COMPLETELY SAFE     │
        └───────────────────────────────────────┘

DATABASE BEFORE:
┌────┬──────────────────┬──────────┬────────┐
│ ID │ URL              │ Parent   │ Status │
├────┼──────────────────┼──────────┼────────┤
│100 │ example.com      │ NULL     │  ✓    │
│101 │ example.com/p1   │ 100      │  ✓    │
│102 │ example.com/p2   │ 100      │  ✓    │ ← DELETE THIS
│103 │ example.com/p3   │ 100      │  ✓    │
└────┴──────────────────┴──────────┴────────┘

DATABASE AFTER:
┌────┬──────────────────┬──────────┬────────┐
│ ID │ URL              │ Parent   │ Status │
├────┼──────────────────┼──────────┼────────┤
│100 │ example.com      │ NULL     │  ✓    │ ← UNTOUCHED
│101 │ example.com/p1   │ 100      │  ✓    │ ← UNTOUCHED
│102 │ example.com/p2   │ 100      │  ✗    │ ← DELETED
│103 │ example.com/p3   │ 100      │  ✓    │ ← UNTOUCHED
└────┴──────────────────┴──────────┴────────┘

DATA DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ PostgreSQL:  1 record (child only)
✗ Celery:      1 task
✗ Redis:       1 crawling state
✗ S3:          2 files (temp HTML + markdown)
✗ Gemini:      1 FileSearch document

DATA UNTOUCHED (SAFE ✅):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ PostgreSQL:  Parent (100) + Siblings (101, 103)
✓ Celery:      Parent + Sibling tasks
✓ Redis:       Parent + Sibling states
✓ S3:          Parent + Sibling files
✓ Gemini:      Parent + Sibling documents

RESPONSE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "success": true,
  "is_parent": false,           ← Shows this was a CHILD
  "child_pages_count": 0,        ← No children affected
  "cleanup_summary": {
    "db_records_affected": 1,    ← Only 1 record
    "celery_tasks_revoked": 1,
    "s3_files_deleted": 2,
    "gemini_docs_deleted": 1
  }
}
```

---

## 4️⃣ Scenario 4: Single Web Page Deletion (Not Part of Website Tree)

```
┌──────────────────────────────────────────────────────────────────────────┐
│         DELETE SINGLE WEB PAGE (No Parent, No Children)                  │
│              Example: Single URL web crawl with no children               │
└──────────────────────────────────────────────────────────────────────────┘

                         User Clicks Delete
                     on Single Web Page Entry
                              ↓
                  ┌──────────────────────────────┐
                  │ API: DELETE /website/50       │
                  │ (Single page, parent_id=NULL)│
                  └──────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 1: DETECT THIS IS A PARENT                 │
      │ SELECT parent_id FROM scraped_websites           │
      │ WHERE id = 50                                    │
      │                                                  │
      │ Result: parent_id = NULL → IS PARENT ✓          │
      │ (But has no children)                            │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 2: FETCH CHILD PAGES                       │
      │ SELECT id FROM scraped_websites                 │
      │ WHERE parent_id = 50                            │
      │                                                  │
      │ Result: [] (empty - no children)                │
      │ → Only this single page will be deleted         │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 3: REVOKE CELERY TASK                      │
      │ ✗ Single page (50) crawling task                 │
      │                                                  │
      │ all_pages = [page_50]  (1 item)                 │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 4: CANCEL REDIS STATE                      │
      │ DEL website:crawling:50                         │
      │ DEL all_metadata_for_50                         │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 5: DELETE FROM S3                          │
      │ ✗ Temp HTML for page 50                         │
      │ ✗ Processed markdown for page 50                │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 6: DELETE FROM GEMINI                      │
      │ ✗ FileSearch document for page 50               │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 7: DATABASE DELETE                         │
      │ BEGIN TRANSACTION                                │
      │  ✗ UPDATE scraped_websites                       │
      │    SET status = 'deleted'                        │
      │    WHERE id = 50                                 │
      │  (No children to delete)                         │
      │ COMMIT                                           │
      └──────────────────────────────────────────────────┘
                              ↓
        ┌───────────────────────────────────────┐
        │       SUCCESS ✅                      │
        │  Single page 50 deleted               │
        │  No family relationships to manage    │
        └───────────────────────────────────────┘

DATA DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ PostgreSQL:  1 record (single page)
✗ Celery:      1 task
✗ Redis:       1 state
✗ S3:          2 files
✗ Gemini:      1 document

UNAFFECTED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Other single pages (independent)
✓ Website trees (different parent_id)
✓ Files (different table)

RESPONSE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "success": true,
  "is_parent": true,       ← Parent (but no children)
  "child_pages_count": 0,  ← No children
  "cleanup_summary": {
    "db_records_affected": 1,
    "celery_tasks_revoked": 1,
    "s3_files_deleted": 2,
    "gemini_docs_deleted": 1
  }
}
```

---

## 5️⃣ Scenario 5: Top-Level Sitemap Deletion

```
┌──────────────────────────────────────────────────────────────────────────┐
│       DELETE TOP-LEVEL SITEMAP XML + ALL EXTRACTED URLs                 │
│       Example: Delete sitemap.xml (parent) with 50 extracted URLs       │
└──────────────────────────────────────────────────────────────────────────┘

                         User Clicks Delete
                      on Sitemap XML Entry
                              ↓
                ┌────────────────────────────────┐
                │ API: DELETE /website/1000       │
                │ (Sitemap XML - parent_id=NULL) │
                └────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 1: DETECT THIS IS A SITEMAP (PARENT)         │
    │ SELECT parent_id, scraped_type FROM scraped_websites│
    │ WHERE id = 1000                                     │
    │                                                     │
    │ Result: parent_id = NULL, type = "sitemap"         │
    │ → IS PARENT SITEMAP ✓                             │
    └─────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 2: FETCH ALL SITEMAP URLS (children)         │
    │ SELECT id FROM scraped_websites                    │
    │ WHERE parent_id = 1000                             │
    │                                                     │
    │ Result: [1001, 1002, ..., 1050] (50 URLs)         │
    │ → 50 child pages extracted from sitemap           │
    └─────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 3: REVOKE ALL CELERY TASKS                    │
    │ ✗ Sitemap processing task (1000)                    │
    │ ✗ URL extraction task                               │
    │ ✗ All 50 URL crawling tasks (1001-1050)            │
    │ ✗ All docling processing tasks                      │
    │                                                     │
    │ Total: ~50+ tasks revoked                           │
    └─────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 4: CANCEL REDIS STATES                        │
    │ DEL sitemap:processing:1000                        │
    │ DEL extraction:progress:1000                       │
    │ DEL website:crawling:1001 to :1050                │
    │ (DEL all 50 child crawling states)                 │
    │ DEL all_celery_task_states                         │
    └─────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 5: DELETE FROM S3 (PARENT + ALL CHILDREN)     │
    │ ✗ Sitemap XML file (1000)                           │
    │ ✗ Sitemap processed content (1000)                  │
    │ ✗ All 50 URL temp HTML files                        │
    │ ✗ All 50 URL processed markdown files               │
    │                                                     │
    │ Total files: ~102 S3 files deleted                 │
    └─────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 6: DELETE FROM GEMINI (PARENT + ALL CHILDREN) │
    │ ✗ Sitemap XML FileSearch document (1000)            │
    │ ✗ All 50 extracted URL FileSearch documents         │
    │                                                     │
    │ Total: 51 FileSearch documents deleted             │
    └─────────────────────────────────────────────────────┘
                              ↓
    ┌─────────────────────────────────────────────────────┐
    │ STEP 7: ATOMIC DATABASE TRANSACTION                │
    │ BEGIN TRANSACTION                                   │
    │  ✗ UPDATE sitemap (1000): status = 'deleted'       │
    │  ✗ UPDATE all URLs: status = 'deleted'             │
    │    (WHERE parent_id = 1000)                        │
    │  ✗ Delete all metadata for 51 items                │
    │  ✗ Delete search associations                      │
    │ COMMIT (all-or-nothing)                            │
    │                                                     │
    │ Total records: 51 deleted                          │
    └─────────────────────────────────────────────────────┘
                              ↓
        ┌───────────────────────────────────────────┐
        │        SUCCESS ✅                         │
        │ Sitemap + 50 URLs completely removed      │
        │ Total: 51 records + 102 files + 51 docs  │
        └───────────────────────────────────────────┘

STRUCTURE BEFORE:
┌──────────────────────────────────┐
│  Sitemap XML (ID: 1000)          │
│  parent_id = NULL                │
│                                  │
│  ├─ URL 1 (ID: 1001)             │
│  ├─ URL 2 (ID: 1002)             │
│  ├─ URL 3 (ID: 1003)             │
│  ...                             │
│  └─ URL 50 (ID: 1050)            │
└──────────────────────────────────┘
         (51 total records)

AFTER DELETION:
┌──────────────────────────────────┐
│      ALL DELETED ✗               │
│  Sitemap + all 50 URLs gone      │
│  Zero records remaining          │
└──────────────────────────────────┘

DATA DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ PostgreSQL:    51 records (1 sitemap + 50 URLs)
✗ Celery:        ~50+ tasks (extraction + crawling)
✗ Redis:         51 crawling states + metadata
✗ S3:            ~102 files (2 per URL × 50 + 2 for sitemap)
✗ Gemini:        51 FileSearch documents
✗ Local:         Temp files cleaned

UNAFFECTED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ Other sitemaps (different parent)
✓ Website trees (different parent)
✓ File uploads (different table)

RESPONSE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "success": true,
  "is_parent": true,
  "child_pages_count": 50,
  "cleanup_summary": {
    "db_records_affected": 51,
    "celery_tasks_revoked": 50,
    "s3_files_deleted": 102,
    "gemini_docs_deleted": 51
  }
}
```

---

## 6️⃣ Scenario 6: Child Page of Sitemap Deletion (Keep Other URLs)

```
┌──────────────────────────────────────────────────────────────────────────┐
│        DELETE SINGLE URL FROM SITEMAP (Other URLs Safe)                 │
│  Example: Delete one extracted URL from sitemap while keeping others     │
└──────────────────────────────────────────────────────────────────────────┘

                         User Clicks Delete
                     on Sitemap Child URL Entry
                              ↓
                ┌────────────────────────────────┐
                │ API: DELETE /website/1025       │
                │ (Child of sitemap 1000)        │
                └────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 1: DETECT THIS IS A CHILD                  │
      │ SELECT parent_id FROM scraped_websites           │
      │ WHERE id = 1025                                  │
      │                                                  │
      │ Result: parent_id = 1000 → IS CHILD ✓           │
      │ (Has parent sitemap 1000)                       │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 2: SKIP CHILD FETCH                        │
      │ (Because is_parent = False)                      │
      │                                                  │
      │ child_pages = []  (empty)                        │
      │ → Only this URL will be deleted                │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 3: REVOKE CELERY TASK (CHILD ONLY)         │
      │ ✗ URL 1025 crawling task                         │
      │                                                  │
      │ KEEP:                                            │
      │ ✓ Sitemap (1000) task - UNTOUCHED               │
      │ ✓ URL 1024 task - UNTOUCHED                      │
      │ ✓ URL 1026 task - UNTOUCHED                      │
      │ ✓ All other URL tasks - UNTOUCHED               │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 4: CANCEL REDIS STATE (CHILD ONLY)         │
      │ DEL website:crawling:1025                       │
      │                                                  │
      │ KEEP:                                            │
      │ ✓ Sitemap (1000) state - UNTOUCHED              │
      │ ✓ Other URLs states - UNTOUCHED                 │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 5: DELETE FROM S3 (CHILD ONLY)             │
      │ ✗ URL 1025 temp HTML                             │
      │ ✗ URL 1025 processed markdown                    │
      │                                                  │
      │ KEEP IN S3:                                      │
      │ ✓ Sitemap (1000) files - UNTOUCHED              │
      │ ✓ URL 1024 files - UNTOUCHED                    │
      │ ✓ URL 1026 files - UNTOUCHED                    │
      │ ✓ All other URL files - UNTOUCHED               │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 6: DELETE FROM GEMINI (CHILD ONLY)         │
      │ ✗ URL 1025 FileSearch document                   │
      │                                                  │
      │ KEEP IN GEMINI:                                  │
      │ ✓ Sitemap (1000) doc - UNTOUCHED                │
      │ ✓ URL 1024 doc - UNTOUCHED                      │
      │ ✓ URL 1026 doc - UNTOUCHED                      │
      │ ✓ All other URL docs - UNTOUCHED                │
      └──────────────────────────────────────────────────┘
                              ↓
      ┌──────────────────────────────────────────────────┐
      │ STEP 7: DATABASE DELETE (CHILD ONLY)            │
      │ BEGIN TRANSACTION                                │
      │  ✗ UPDATE scraped_websites                       │
      │    SET status = 'deleted'                        │
      │    WHERE id = 1025                               │
      │  (No children of 1025)                           │
      │ COMMIT                                           │
      └──────────────────────────────────────────────────┘
                              ↓
        ┌───────────────────────────────────────────┐
        │         SUCCESS ✅                        │
        │ URL 1025 deleted ONLY                     │
        │ Sitemap + other URLs COMPLETELY SAFE      │
        └───────────────────────────────────────────┘

STRUCTURE BEFORE:
┌──────────────────────────────────┐
│  Sitemap XML (ID: 1000)          │
│                                  │
│  ├─ URL 1024 (ID: 1024)          │
│  ├─ URL 1025 (ID: 1025) ← DELETE │
│  ├─ URL 1026 (ID: 1026)          │
│  ...                             │
│  └─ URL 1050 (ID: 1050)          │
└──────────────────────────────────┘
       (51 records total)

STRUCTURE AFTER:
┌──────────────────────────────────┐
│  Sitemap XML (ID: 1000) ✓        │
│                                  │
│  ├─ URL 1024 (ID: 1024) ✓        │
│  ├─ URL 1026 (ID: 1026) ✓        │
│  ...                             │
│  └─ URL 1050 (ID: 1050) ✓        │
└──────────────────────────────────┘
    (50 records remain - safe!)

DATA DELETED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ PostgreSQL:  1 record (URL 1025 only)
✗ Celery:      1 task
✗ Redis:       1 crawling state
✗ S3:          2 files (temp HTML + markdown)
✗ Gemini:      1 FileSearch document

DATA UNTOUCHED (SAFE ✅):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ PostgreSQL:  Sitemap (1000) + 49 other URLs
✓ Celery:      Sitemap + 49 other URL tasks
✓ Redis:       Sitemap + 49 other URL states
✓ S3:          Sitemap + 49 other URL files
✓ Gemini:      Sitemap + 49 other URL documents

RESPONSE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{
  "success": true,
  "is_parent": false,          ← Shows this was a CHILD
  "child_pages_count": 0,       ← No children (it's a leaf)
  "cleanup_summary": {
    "db_records_affected": 1,   ← Only 1 record
    "celery_tasks_revoked": 1,
    "s3_files_deleted": 2,
    "gemini_docs_deleted": 1
  }
}
```

---

# Summary Comparison Table

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                  DELETION SCENARIOS - COMPARISON                            │
├──────┬──────────────────────┬─────────────┬─────────────┬──────────────────┤
│      │  SCENARIO            │ PARENT ONLY │ PARENT TYPE │ DB RECORDS       │
├──────┼──────────────────────┼─────────────┼─────────────┼──────────────────┤
│ 1️⃣   │ File Upload          │    N/A      │   File      │  1 file          │
│      │                      │             │             │  DELETED         │
├──────┼──────────────────────┼─────────────┼─────────────┼──────────────────┤
│ 2️⃣   │ Website + Children   │    YES      │   Website   │  1 parent +      │
│      │                      │             │             │  3 children      │
│      │                      │             │             │  DELETED (4)     │
├──────┼──────────────────────┼─────────────┼─────────────┼──────────────────┤
│ 3️⃣   │ Child Page Only      │    NO       │   Website   │  1 child         │
│      │ (Siblings Safe)      │             │             │  DELETED         │
│      │                      │             │             │  Parent + 2      │
│      │                      │             │             │  siblings SAFE   │
├──────┼──────────────────────┼─────────────┼─────────────┼──────────────────┤
│ 4️⃣   │ Single Web Page      │    YES      │   Website   │  1 page          │
│      │ (No children)        │             │             │  DELETED         │
├──────┼──────────────────────┼─────────────┼─────────────┼──────────────────┤
│ 5️⃣   │ Sitemap + All URLs   │    YES      │   Sitemap   │  1 sitemap +     │
│      │                      │             │             │  50 URLs         │
│      │                      │             │             │  DELETED (51)    │
├──────┼──────────────────────┼─────────────┼─────────────┼──────────────────┤
│ 6️⃣   │ Single URL from      │    NO       │   Sitemap   │  1 URL           │
│      │ Sitemap             │             │             │  DELETED         │
│      │ (Other URLs Safe)    │             │             │  Sitemap + 49    │
│      │                      │             │             │  URLs SAFE       │
└──────┴──────────────────────┴─────────────┴─────────────┴──────────────────┘
```

---

# Key Detection Logic

All scenarios use the same **auto-detection mechanism**:

```python
# STEP 1: Detect parent vs child
website_record = await conn.fetchrow(
    "SELECT parent_id FROM scraped_websites WHERE id = $1",
    website_id
)

is_parent = website_record['parent_id'] is None
#  parent_id = NULL  → is_parent = True  (parent/root)
#  parent_id = 100   → is_parent = False (child/leaf)

# STEP 2: Fetch children ONLY if parent
child_pages = []
if is_parent:
    child_pages = await conn.fetch(
        "SELECT id FROM scraped_websites WHERE parent_id = $1",
        website_id
    )

# STEP 3: Delete atomically
all_pages = [website_record] + child_pages

# If is_parent=False: all_pages = [single_record]
# If is_parent=True:  all_pages = [parent] + [children...]
```

**Result**:
- Deleting a child: `child_pages=[]` → only 1 record updated ✅
- Deleting a parent: `child_pages=[...]` → parent + children updated together ✅
- Siblings always safe: Different parent_id → unaffected ✅

---

# Atomic Transaction Pattern

All deletions use this pattern for safety:

```python
async with conn.transaction():
    # 1. Delete main item
    await conn.execute(
        "UPDATE scraped_websites SET processing_status = 'deleted' WHERE id = $1",
        website_id
    )

    # 2. Delete children ONLY if this is a parent with children
    if child_pages:  # Only executes if child_pages is not empty
        await conn.execute(
            "UPDATE scraped_websites SET processing_status = 'deleted' WHERE parent_id = $1",
            website_id
        )

    # 3. Delete metadata (executes for all scenarios)
    # ... delete from metadata, search associations, etc

# If ANY step fails: ROLLBACK (all-or-nothing)
```

**Safety Guarantees**:
- ✅ All-or-nothing: Either everything deletes or nothing does
- ✅ No partial deletes: No orphaned records
- ✅ No race conditions: Row-level locking with FOR UPDATE
- ✅ Consistent family relationships: Parent/child bonds maintained
