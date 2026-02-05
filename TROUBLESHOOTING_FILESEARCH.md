# FileSearch Issues Troubleshooting Guide

## ✅ AUTOMATIC INITIALIZATION (v2.0)

**Good news!** The FileSearch store is now **automatically created on service startup**. You no longer need to run manual initialization scripts!

When the knowledgebase_ingestion or website_crawling services start, they will:
1. Check if the FileSearch store exists
2. Create it automatically if it doesn't exist
3. Log the store status in the startup logs

---

## 🔴 Issues Identified

You're experiencing 4 interconnected problems, all stemming from a missing Gemini FileSearch store:

### 1. Gemini Upload Failing for Scraped Websites
```json
"gemini_file": null,
"gemini_state": "FAILED"
```

### 2. Unable to Get Answers from RAG FileSearch
```
400 INVALID_ARGUMENT: Either this resource does not exist or it does not support permission management.
```

### 3. Unable to Delete Crawled URLs from UI
Frontend's delete method only works for uploaded files, not scraped websites.

### 4. All File Uploads May Be Failing
Same root cause as #1 - FileSearch store doesn't exist.

---

## 🎯 Root Cause

The **FileSearch store** `knowledgebot-search-store` **doesn't exist** in your Gemini project. All the code assumes this store exists and tries to:
- Upload files to it
- Upload scraped content to it
- Search it for RAG queries

But the store was never created!

---

## ✅ Solution 1: Automatic Initialization (Recommended)

**The store is now auto-created on service startup!** Just ensure your environment is configured correctly:

### Step 1: Verify Your .env File

Ensure your `.env` file has:
```bash
GEMINI_API_KEY=your_actual_api_key_here
GEMINI_FILE_SEARCH_STORE_NAME=knowledgebot-search-store
```

### Step 2: Deploy/Restart Services

The store will be created automatically when services start:

**If using Railway:**
- Push to GitHub triggers automatic redeploy
- Services will auto-create the store on startup

**If running locally:**
```bash
# Start services - store is created automatically
docker-compose up
# OR
python -m uvicorn knowledgebase_ingestion.main:app --port 8001
python -m uvicorn website_crawling.main:app --port 8002
```

### Step 3: Check Startup Logs

You should see in the logs:
```
✅ Gemini client initialized
🔍 Checking FileSearch store: knowledgebot-search-store
🔨 Creating FileSearch store: knowledgebot-search-store
✅ FileSearch store created successfully: fileSearchStores/abc123
✅ FileSearch store ready: fileSearchStores/abc123
🚀 Knowledgebase ingestion service started successfully
```

---

## ✅ Solution 1-B: Manual Initialization (If Needed)

If automatic initialization fails, you can still run the manual script:

```bash
cd /path/to/knowledgebot-railway-backend
python initialize_file_search_store.py
```

This is only needed if:
- Automatic initialization is failing
- You want to verify the store before starting services
- You're debugging FileSearch issues

---

## ✅ Solution 2: Fix Delete Functionality for Scraped Websites

The frontend's delete function needs to differentiate between uploaded files and scraped websites.

### Current Issue:
- `deleteFile()` in `KnowledgeBaseManagement.tsx` (line 111) only calls `/files/{id}`
- For scraped websites, it should call `/webcrawl/jobs/{id}`

### Fix Required:
Update the `deleteFile` method in the `KnowledgeBaseService` class to check the file source:

```typescript
async deleteFile(fileId: string, source?: string): Promise<any> {
  // Determine endpoint based on source
  let deleteUrl;
  if (source === 'scrape') {
    // Use webcrawl endpoint for scraped websites
    deleteUrl = `${this.baseUrl.replace('/knowledgebase', '/webcrawl')}/jobs/${fileId}`;
  } else {
    // Use files endpoint for uploaded files
    const cleanFileId = fileId.replace(/^files\//, '').replace(/:\d+$/, '');
    deleteUrl = `${this.baseUrl}/files/${encodeURIComponent(cleanFileId)}`;
  }

  const headers = await this.getAuthHeaders();
  const response = await fetch(deleteUrl, {
    method: 'DELETE',
    headers: headers,
  });

  // ... rest of the method
}
```

Then update the call site (line 787):
```typescript
const result = await knowledgeBaseService.deleteFile(itemToDelete.id, itemToDelete.source);
```

---

## ✅ Solution 3: Verify Gemini API Access

Ensure your Gemini API key has access to the FileSearch API:

1. Go to [Google AI Studio](https://aistudio.google.com/)
2. Check your API key permissions
3. Verify FileSearch API is enabled

---

## 🔍 How to Test

### Test 1: Initialize Store
```bash
python initialize_file_search_store.py
```

Expected output:
```
✅ Gemini client initialized
✅ FileSearch store created successfully!
   Store ID: fileSearchStores/abc123xyz
   Display Name: knowledgebot-search-store
🎉 Initialization complete!
```

### Test 2: Upload a File
Try uploading a PDF through your frontend. Check logs for:
```
🤖 [GEMINI] Uploading file - Display: your_file.pdf
📂 [GEMINI] Uploading to FileSearch store: knowledgebot-search-store
🔄 [GEMINI] FileSearch operation state: ACTIVE
✅ [GEMINI] FileSearch upload complete - Content is now ACTIVE
```

### Test 3: Scrape a Website
Try scraping a URL. Check logs for:
```
🤖 [GEMINI] Uploading scraped content - Display: Page Title | https://example.com
📂 [GEMINI] Uploading to FileSearch store: knowledgebot-search-store
✅ [GEMINI] FileSearch upload complete - Content is now ACTIVE
```

### Test 4: Ask a Question
Try asking a question about your uploaded content. Check logs for:
```
🔍 Performing RAG search in knowledge base...
📂 Using FileSearch store: fileSearchStores/knowledgebot-search-store
✅ Generated response length: XXX characters
```

---

## 🐛 Common Errors and Solutions

### Error: "GEMINI_API_KEY not found"
**Solution:** Add your API key to `.env`:
```bash
GEMINI_API_KEY=your_key_here
```

### Error: "file_search_stores API not available"
**Solution:** Upgrade google-genai:
```bash
pip install --upgrade google-genai
```

### Error: "403 Permission Denied"
**Solution:** Your API key doesn't have FileSearch access. Create a new key in Google AI Studio with FileSearch enabled.

### Error: "404 Store not found" (after creating store)
**Solution:** The store was created but the name format is wrong. Check the output of the init script and update your `.env` with the exact store name returned.

---

## 📊 Checklist

- [ ] Run `initialize_file_search_store.py`
- [ ] Verify FileSearch store was created
- [ ] Update `.env` with correct `GEMINI_API_KEY`
- [ ] Restart all services
- [ ] Test file upload
- [ ] Test website scraping
- [ ] Test RAG search
- [ ] Fix frontend delete functionality (if needed)
- [ ] Test deleting scraped websites

---

## 📞 Still Having Issues?

If problems persist:
1. Check the logs from `initialize_file_search_store.py`
2. Verify your Gemini API quota hasn't been exceeded
3. Ensure you're using the latest `google-genai` package version
4. Check that your Railway environment has the correct `GEMINI_API_KEY` set

---

## 🎉 Success Indicators

You'll know everything is working when:
1. ✅ File uploads show `gemini_state: "ACTIVE"`
2. ✅ Scraped websites show `gemini_file: "files/abc123"` (not null)
3. ✅ RAG search returns relevant answers
4. ✅ Delete works for both files and scraped websites
5. ✅ No more "400 INVALID_ARGUMENT" errors in logs
