# Frontend Implementation - Duplicate Detection Confirm Dialog

## 📋 Overview

When a user uploads a duplicate file, the frontend should:
1. Catch the 409 Conflict response
2. Show a confirm dialog asking: "This file already exists. Replace it?"
3. If user confirms → Delete old file first, then upload new file
4. Show progress at each step

---

## 🔌 API Response Format

### Success (200 OK)
```json
{
  "success": true,
  "file_id": "456",
  "status": "pending",
  "message": "File uploaded successfully"
}
```

### Duplicate Detected (409 Conflict)
```json
{
  "success": false,
  "error": "File already exists",
  "reason": "filename_exists",
  "match_type": "filename",
  "detail": "File 'document.pdf' already exists (Status: completed)",
  "existing_file_id": "123",
  "existing_file_name": "document.pdf"
}
```

### Other Validation Errors (400 Bad Request)
```json
{
  "error": "File size exceeds maximum allowed size"
}
```

---

## 🎨 React Component Implementation

### 1. File Upload Component with Duplicate Detection

```tsx
import React, { useState } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface DuplicateFile {
  existing_file_id: string;
  existing_file_name: string;
  detail: string;
}

export function FileUploadComponent() {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [duplicate, setDuplicate] = useState<DuplicateFile | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // Step 1: Handle file selection
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setUploadError(null);
    }
  };

  // Step 2: Upload file (detect duplicates)
  const handleUpload = async () => {
    if (!file) return;

    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/v1/knowledgebase/files/upload/async', {
        method: 'POST',
        body: formData,
      });

      if (response.status === 409) {
        // ✅ Duplicate detected - show confirm dialog
        const duplicateData = await response.json();
        setDuplicate({
          existing_file_id: duplicateData.existing_file_id,
          existing_file_name: duplicateData.existing_file_name,
          detail: duplicateData.detail,
        });
        setShowDuplicateDialog(true);
        setIsUploading(false);
        return;
      }

      if (!response.ok) {
        const errorData = await response.json();
        setUploadError(errorData.error || 'Upload failed');
        setIsUploading(false);
        return;
      }

      // ✅ Success - file uploaded
      const result = await response.json();
      console.log('File uploaded:', result);
      setFile(null);
      setUploadError(null);
      // Show success message or refresh list

    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Upload error');
    } finally {
      setIsUploading(false);
    }
  };

  // Step 3: User confirms override
  const handleConfirmOverride = async () => {
    if (!duplicate || !file) return;

    try {
      // Step 3a: Delete old file
      setIsDeleting(true);
      const deleteResponse = await fetch(
        `/api/v1/knowledgebase/files/${duplicate.existing_file_id}`,
        { method: 'DELETE' }
      );

      if (!deleteResponse.ok) {
        setUploadError('Failed to delete existing file. Please try again.');
        setShowDuplicateDialog(false);
        return;
      }

      // Step 3b: Upload new file after deletion
      const formData = new FormData();
      formData.append('file', file);

      const uploadResponse = await fetch('/api/v1/knowledgebase/files/upload/async', {
        method: 'POST',
        body: formData,
      });

      if (!uploadResponse.ok) {
        const errorData = await uploadResponse.json();
        setUploadError(errorData.error || 'Upload failed after deletion');
        setShowDuplicateDialog(false);
        return;
      }

      // ✅ Success
      const result = await uploadResponse.json();
      console.log('File replaced:', result);
      setFile(null);
      setDuplicate(null);
      setShowDuplicateDialog(false);
      setUploadError(null);
      // Show success message or refresh list

    } catch (error) {
      setUploadError(error instanceof Error ? error.message : 'Error during replacement');
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* File Input */}
      <div className="border-2 border-dashed border-gray-300 rounded-lg p-6">
        <input
          type="file"
          onChange={handleFileSelect}
          disabled={isUploading || isDeleting}
          className="w-full"
        />
        {file && <p className="mt-2 text-sm text-gray-600">Selected: {file.name}</p>}
      </div>

      {/* Error Message */}
      {uploadError && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 rounded">
          {uploadError}
        </div>
      )}

      {/* Upload Button */}
      <button
        onClick={handleUpload}
        disabled={!file || isUploading || isDeleting}
        className="bg-blue-500 text-white px-4 py-2 rounded disabled:opacity-50"
      >
        {isUploading ? 'Uploading...' : 'Upload File'}
      </button>

      {/* Duplicate Confirm Dialog */}
      <AlertDialog open={showDuplicateDialog} onOpenChange={setShowDuplicateDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>File Already Exists</AlertDialogTitle>
            <AlertDialogDescription>
              <div className="space-y-3">
                <p>This file already exists in your knowledge base:</p>
                <div className="bg-gray-50 p-3 rounded text-sm text-gray-900">
                  <p className="font-semibold">{duplicate?.existing_file_name}</p>
                  <p className="text-gray-600">{duplicate?.detail}</p>
                </div>
                <p className="font-medium">Do you want to replace it with the new version?</p>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialog.Footer>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmOverride}
              disabled={isDeleting}
              className="bg-red-500 hover:bg-red-600"
            >
              {isDeleting ? 'Replacing...' : 'Replace File'}
            </AlertDialogAction>
          </AlertDialog.Footer>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
```

---

## 🔄 State Flow Diagram

```
┌──────────────────┐
│ User selects     │
│ file             │
└────────┬─────────┘
         │
         ▼
    ┌────────────┐
    │ User clicks│
    │ "Upload"   │
    └────┬───────┘
         │
         ▼
    ┌──────────────────────────┐
    │ POST /upload/async       │
    │ (with file)              │
    └────┬─────────────────────┘
         │
     ┌───┴──────────┐
     │              │
  200 OK        409 Conflict
     │              │
     │              ▼
     │        ┌──────────────────┐
     │        │ Show confirm      │
     │        │ dialog:           │
     │        │ "Replace file?"   │
     │        │ [Cancel] [Replace]
     │        └────┬─────────────┘
     │             │
     │         ┌───┴─────────────┐
     │      Cancel            Confirm
     │         │                 │
     │         ▼                 ▼
     │    Dismiss dialog   ┌──────────────────┐
     │                     │ DELETE /files/ID │
     │                     │ (old file)       │
     │                     └────┬─────────────┘
     │                          │
     │                          ▼
     │                     ┌──────────────────┐
     │                     │ POST /upload/    │
     │                     │ async (new file) │
     │                     └────┬─────────────┘
     │                          │
     │                      ✅ Success
     │                          │
     ▼                          ▼
  ┌─────────────────────────────────┐
  │ Show success message             │
  │ Refresh file list / table        │
  │ Clear upload state               │
  └─────────────────────────────────┘
```

---

## 🛠️ Implementation Checklist

### Error Handling
- [ ] Detect 409 status code from upload endpoint
- [ ] Extract duplicate file info from response
- [ ] Handle delete endpoint errors
- [ ] Handle upload endpoint errors
- [ ] Show error messages to user

### Dialog States
- [ ] Show dialog only on 409 response
- [ ] Hide dialog on cancel
- [ ] Hide dialog on successful replacement
- [ ] Disable buttons during deletion/upload

### User Feedback
- [ ] Show "Uploading..." while uploading
- [ ] Show "Replacing..." while deleting and re-uploading
- [ ] Show file details in confirm dialog
- [ ] Show error messages for failures

### Data Management
- [ ] Clear file input after success
- [ ] Clear error messages after new upload
- [ ] Store duplicate info temporarily
- [ ] Reset state on dialog close

---

## 🔧 Advanced: Custom Hook

You can also create a custom hook for cleaner component code:

```tsx
import { useState } from 'react';

interface UploadOptions {
  onSuccess?: (result: any) => void;
  onError?: (error: string) => void;
}

export function useFileUploadWithDuplicateDetection(options: UploadOptions = {}) {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [duplicate, setDuplicate] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = async (fileToUpload: File) => {
    setIsUploading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', fileToUpload);

    try {
      const response = await fetch('/api/v1/knowledgebase/files/upload/async', {
        method: 'POST',
        body: formData,
      });

      if (response.status === 409) {
        const data = await response.json();
        setDuplicate(data);
        setShowDuplicateDialog(true);
        return false;
      }

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Upload failed');
      }

      const result = await response.json();
      setFile(null);
      options.onSuccess?.(result);
      return true;

    } catch (err) {
      const message = err instanceof Error ? err.message : 'Upload error';
      setError(message);
      options.onError?.(message);
      return false;

    } finally {
      setIsUploading(false);
    }
  };

  const confirmReplace = async () => {
    if (!duplicate || !file) return;

    setIsDeleting(true);
    try {
      // Delete old file
      const deleteResponse = await fetch(
        `/api/v1/knowledgebase/files/${duplicate.existing_file_id}`,
        { method: 'DELETE' }
      );

      if (!deleteResponse.ok) throw new Error('Delete failed');

      // Upload new file
      await upload(file);

    } catch (err) {
      const message = err instanceof Error ? err.message : 'Replacement failed';
      setError(message);
      options.onError?.(message);

    } finally {
      setIsDeleting(false);
    }
  };

  return {
    file,
    setFile,
    isUploading,
    isDeleting,
    error,
    showDuplicateDialog,
    setShowDuplicateDialog,
    duplicate,
    upload,
    confirmReplace,
  };
}
```

Usage in component:
```tsx
const { file, setFile, upload, showDuplicateDialog, confirmReplace, error } =
  useFileUploadWithDuplicateDetection({
    onSuccess: () => alert('File uploaded!'),
    onError: (err) => alert(`Error: ${err}`),
  });
```

---

## 📱 UI Framework Examples

### Using shadcn/ui
```tsx
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
```

### Using Headless UI
```tsx
import { Dialog, Transition } from '@headlessui/react';
```

### Using Material-UI
```tsx
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Button,
} from '@mui/material';
```

---

## 📊 Example Flow

```
User: "I'm uploading document.pdf"

Frontend: POST /upload/async with document.pdf
Backend: Finds existing document.pdf (ID: 656, Status: completed)
Backend: Returns 409 Conflict with duplicate details

Frontend: Detects 409 status code
Frontend: Shows dialog:
  "File Already Exists"
  "This file already exists: document.pdf (Status: completed)"
  [Cancel] [Replace File]

User: Clicks [Replace File]
Frontend: DELETE /files/656
Backend: Soft deletes file 656 (status='deleted')
Frontend: Waits for 200 OK response

Frontend: POST /upload/async with document.pdf (new)
Backend: No duplicate found (old one deleted)
Backend: Returns 200 OK with new file_id=789

Frontend: Shows success:
  "File replaced successfully! Processing..."
  Clear input
  Refresh file list
```

---

## ✅ Testing Checklist

- [ ] Upload unique file → Success
- [ ] Upload duplicate file → Show dialog
- [ ] Click Cancel on dialog → Upload cancelled, original stays
- [ ] Click Replace → Delete old, upload new
- [ ] Delete fails → Show error, don't proceed with upload
- [ ] Upload fails after delete → Show error, old file already deleted
- [ ] Network error → Show error, allow retry

---

## Summary

**Key Points:**
1. ✅ Backend returns 409 Conflict for duplicates
2. ✅ Frontend detects 409 status code
3. ✅ Show confirm dialog with duplicate file info
4. ✅ User confirms → Delete old file → Upload new file
5. ✅ Show progress and error messages
6. ✅ Handle all error scenarios

**Files to Update in Your Frontend:**
- File upload component
- API client/fetch wrapper (optional)
- Dialog/modal component
- File list refresh after upload

This gives users full control and visibility over the override process! 🎉
