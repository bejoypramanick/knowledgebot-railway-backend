# RAG Search Troubleshooting Guide

## Problem Summary

RAG search is returning "I'm sorry, but this information is not available in my knowledge base" even though documents may have been uploaded.

## Root Cause Analysis

The issue typically falls into one of these categories:

### 1. **No Documents in FileSearch Store** ❌
- No files have been uploaded yet
- Uploads failed silently
- Files were deleted

### 2. **Files Uploaded but Not in FileSearch** ❌
- Files recorded in PostgreSQL database
- But not actually in Gemini FileSearch store
- Indicates upload to Gemini failed

### 3. **Documents Exist but Query Doesn't Match** ⚠️
- Documents are in FileSearch store
- But query wording doesn't match document content
- FileSearch isn't finding relevance

### 4. **FileSearch Store Misconfigured** ⚠️
- Wrong store ID being used
- Multiple stores created
- Store permissions issue

---

## Diagnostic Steps

### Step 1: Check What's in the Knowledge Base

Run the diagnostic script:

```bash
python rag_diagnostics.py
```

This will show:
- ✅ All Gemini FileSearch stores available
- 📄 Documents currently in the target store
- 🗄️ Files recorded in PostgreSQL
- 🧪 Test RAG query result

### Step 2: Understand the Output

**Expected output if working:**
```
📂 FileSearch store found: fileSearchStores/knowledgebotsearchstore-xxx
📄 Documents in store: 5
   [1] Document ID: files/abc123
       Display Name: document.pdf
       Size: 102400 bytes
```

**Problem signs:**
```
⚠️ NO DOCUMENTS IN STORE!  ← Nothing uploaded
   Total documents: 0
```

```
📁 Files in file_uploads table: 5    ← DB has records but
📄 Documents in FileSearch store: 0  ← Not in Gemini!
```

---

## Common Issues & Solutions

### Issue 1: "No Documents in FileSearch Store"

**Symptoms:**
- rag_diagnostics.py shows 0 documents
- Database has 0 files
- RAG returns: "No relevant documents found"

**Solutions:**

1. **Upload documents first**
   ```bash
   curl -X POST http://localhost:8001/api/v1/knowledgebase/files/upload \
     -F "files=@document.pdf" \
     -H "X-User-Email: admin@example.com"
   ```

2. **Use batch upload for multiple files**
   ```bash
   curl -X POST http://localhost:8001/api/v1/knowledgebase/batchupload \
     -F "files=@file1.pdf" \
     -F "files=@file2.pdf" \
     -F "files=@file3.pdf" \
     -H "X-User-Email: admin@example.com"
   ```

3. **Verify upload succeeded**
   - Check API response has `"success": true`
   - Check logs show "✅ Upload completed"
   - Run rag_diagnostics.py to verify

### Issue 2: "Files in Database But Not in FileSearch"

**Symptoms:**
- Database shows files with `gemini_file_name` populated
- FileSearch store shows 0 documents
- Indicates upload to Gemini failed

**Cause:**
- Gemini API error during upload
- FileSearch store wasn't created
- API quota/rate limit exceeded

**Solutions:**

1. **Check Gemini API key**
   ```bash
   echo $GEMINI_API_KEY
   ```

2. **Verify FileSearch store exists**
   - rag_diagnostics.py should show the store
   - If not found, API Gateway should have created it on startup

3. **Re-upload files**
   - Enable `replace_existing=true` if needed
   - This will delete old DB record and upload fresh

4. **Check Railway logs**
   - Look for "FileSearch" errors in API Gateway startup logs
   - Should see "✅ Resolved FileSearch store ID"

### Issue 3: "Files Exist But RAG Returns No Results"

**Symptoms:**
- rag_diagnostics.py shows documents exist
- But RAG search returns: "No relevant documents found"
- Happens for certain queries but not others

**Cause:**
- Document content doesn't match query keywords
- FileSearch relevance scoring low
- Query is too vague

**Solutions:**

1. **Check document content matches query**
   - If you uploaded "gold hallmarks" document
   - Query "gold and silver hallmarked in 1975" should work
   - But query "spices" might not

2. **Try simpler queries**
   ```
   ❌ Too specific: "What was hallmarked in Britain in 1975?"
   ✅ Better: "hallmarks Britain"
   ✅ Better: "gold silver marks"
   ```

3. **Re-upload with better context**
   - Add metadata/title to documents
   - Use `display_name` parameter with descriptive name
   - Add context around uploaded content

4. **Test raw Gemini without RAG**
   - Ask: "List all documents in my knowledge base"
   - Gemini should show what it found

---

## Log Analysis Guide

### Good RAG Log Output
```
✅ RAG search successful - found relevant information
📄 RAG search response: 156 characters
📄 Response preview: "According to the documents, hallmarks were used in Britain to guarantee..."
📚 Grounding metadata: [shows source documents]
```

### Bad RAG Log Output
```
⚠️ RAG search returned minimal/negative results
📄 RAG search response: 28 characters
📄 Response preview: "No relevant documents found"
⚠️ No grounding metadata
```

---

## Debug Commands

### Check Database Files
```sql
SELECT
  id,
  original_filename,
  gemini_file_name,
  gemini_state,
  created_at
FROM file_uploads
ORDER BY created_at DESC;
```

### Check FileSearch via Python
```python
from google.genai import Client
client = Client(api_key="YOUR_API_KEY")
stores = list(client.file_search_stores.list())
for store in stores:
    print(f"Store: {store.display_name} -> {store.name}")
    files = list(client.file_search_stores.list_files(name=store.name))
    print(f"  Documents: {len(files)}")
```

### Test RAG Manually
```python
from google.genai import Client, types

client = Client(api_key="YOUR_API_KEY")
tool = types.Tool(
    file_search=types.FileSearch(
        file_search_store_names=["fileSearchStores/knowledgebotsearchstore-xxx"]
    )
)

response = client.models.generate_content(
    model="gemini-2.5-flash-lite",
    contents="What information do you have about hallmarks?",
    config=types.GenerateContentConfig(tools=[tool])
)
print(response.text)
```

---

## Quick Checklist

- [ ] At least one PDF/document uploaded
- [ ] Upload API returned `success: true`
- [ ] Logs show "✅ Upload completed"
- [ ] `rag_diagnostics.py` shows documents in FileSearch
- [ ] Documents show `gemini_state: ACTIVE`
- [ ] Query keywords appear in document content
- [ ] GEMINI_API_KEY environment variable is set
- [ ] FileSearch store name matches config
- [ ] No errors in API Gateway logs

---

## Next Steps if Still Not Working

1. **Run rag_diagnostics.py** and share output
2. **Check API Gateway startup logs** for FileSearch initialization
3. **Check chatbot-orchestration logs** for RAG search attempts
4. **Try uploading a test document** with simple known content
5. **Check Gemini API quota** - may be rate limited

---

## Architecture Overview

```
User Query
    ↓
RAG Search (agent_service.py)
    ↓
Gemini FileSearch Tool
    ↓
FileSearch Store (Gemini)
    ↓
    ├─ Document 1 (PDF)
    ├─ Document 2 (PDF)
    └─ Document 3 (PDF)
    ↓
Gemini Response with context
    ↓
Database: Record message + RAG flag
```

**If RAG returns no results, the break is usually between Gemini FileSearch and the FileSearch Store.**

---

## Recent Changes (Feb 2025)

**Latest RAG improvements:**
- Changed from "extract documents" mode to natural FileSearch usage
- Gemini now directly answers questions using FileSearch tool
- Better grounding metadata detection
- Improved logging to show what RAG found
- Added diagnostic script for troubleshooting

This more natural approach should work better with Gemini's FileSearch implementation.
