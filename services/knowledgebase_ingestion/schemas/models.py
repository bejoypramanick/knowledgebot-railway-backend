from pydantic import BaseModel, HttpUrl, Field
from typing import Optional, List, Dict, Any, Union

class FileInfo(BaseModel):
    name: str
    display_name: str
    mime_type: str
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    expiration_time: Optional[str] = None
    size_bytes: Optional[str] = None
    sha256_hash: Optional[str] = None
    uri: Optional[str] = None
    state: Optional[str] = None
    db_record_id: Optional[str] = None
    source: Optional[str] = None  # 'upload' or 'scrape'
    original_filename: Optional[str] = None

class UploadResponse(BaseModel):
    success: bool
    file: Optional[FileInfo] = None
    message: str
    replaced_existing: bool = False

class ValidationError(BaseModel):
    field: str
    message: str

class ValidationResult(BaseModel):
    valid: bool
    errors: List[ValidationError] = []

class BatchUploadItem(BaseModel):
    filename: str
    success: bool
    file: Optional[FileInfo] = None
    message: str
    error: Optional[str] = None
    replaced_existing: bool = False

class BatchUploadResponse(BaseModel):
    success: bool
    total_files: int
    successful_uploads: int
    failed_uploads: int
    results: List[BatchUploadItem]
    message: str
    parallel_processing: bool = True

class BatchDeleteItem(BaseModel):
    file_id: str
    filename: str
    success: bool
    message: str
    error: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

class BatchDeleteResponse(BaseModel):
    success: bool
    total_files: int
    successful_deletes: int
    failed_deletes: int
    results: List[BatchDeleteItem]
    message: str
    parallel_processing: bool = True

class FilesResponse(BaseModel):
    files: List[FileInfo]
