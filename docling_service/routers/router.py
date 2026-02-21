"""Docling Service API Router."""
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Request

from docling_service.core.docling_processor import get_processor
from docling_service.core.config import settings
from docling_service.schemas.models import DoclingProcessResponse, DoclingProcessURLRequest
from docling_service.utils.validation import validate_file_for_processing
from docling_service.utils.constants import MAX_FILE_SIZE_BYTES

logger = logging.getLogger("docling_service")
router = APIRouter()


@router.post("/process")
async def process_document(request: Request, file: UploadFile = File(...)) -> DoclingProcessResponse:
    """
    Convert a document to markdown with image OCR extraction.

    Supports: PDF, DOCX, PPTX, XLSX, HTML, etc.
    Returns markdown content with embedded image OCR text.
    """
    temp_file_path = None

    try:
        # Validate filename
        if not file.filename:
            raise HTTPException(status_code=400, detail="Filename is required")

        # Read file content
        content = await file.read()
        file_size = len(content)

        # Validate file for processing
        is_valid, error_msg = validate_file_for_processing(file.filename, file_size)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)

        # Create temporary file
        import tempfile
        fd, temp_file_path = tempfile.mkstemp(suffix=os.path.splitext(file.filename)[1])
        with os.fdopen(fd, 'wb') as tmp:
            tmp.write(content)

        logger.info(
            f"📄 Processing: {file.filename} "
            f"({file_size / 1024:.1f}KB, timeout={settings.docling_processing_timeout_seconds}s)"
        )

        # Get processor
        processor = await get_processor()

        # Process document
        markdown_content, metadata = await processor.process_document(
            file_path=temp_file_path,
            original_filename=file.filename,
            timeout_seconds=settings.docling_processing_timeout_seconds
        )

        # Handle processing errors
        if not markdown_content:
            error_msg = metadata.get("error", "Unknown error")
            logger.warning(f"⚠️ Processing failed for {file.filename}: {error_msg}")
            # Raise exception instead of returning 200 with success=False
            raise HTTPException(
                status_code=422,
                detail=f"Conversion failed: {error_msg}"
            )

        logger.info(f"✅ Successfully processed: {file.filename}")

        return DoclingProcessResponse(
            success=True,
            content=markdown_content,
            metadata=metadata,
            error=None
        )

    except HTTPException as http_exc:
        logger.error(f"❌ HTTP Exception processing {file.filename}: {http_exc.status_code} - {http_exc.detail}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error processing {file.filename}: {e}")
        import traceback
        logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected processing error: {str(e)}"
        )

    finally:
        # Cleanup temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp file {temp_file_path}: {e}")
        
        # Force garbage collection to free memory
        import gc
        gc.collect()
        logger.debug("🧹 Garbage collection completed")


@router.post("/process_url")
async def process_document_from_url(request: Request, request_data: DoclingProcessURLRequest) -> DoclingProcessResponse:
    """
    Convert a document to markdown using a presigned URL.
    
    This endpoint passes the presigned URL directly to docling's convert() method,
    eliminating the need for file downloads and temporary files.
    
    Args:
        request_data: Contains presigned_url, filename, and mime_type
    
    Returns:
        DoclingProcessResponse with markdown content and metadata
    """
    try:
        # Validate input
        if not request_data.presigned_url:
            raise HTTPException(status_code=400, detail="presigned_url is required")
        if not request_data.filename:
            raise HTTPException(status_code=400, detail="filename is required")
        if not request_data.mime_type:
            raise HTTPException(status_code=400, detail="mime_type is required")
        
        logger.info(f"🔍 [DOCLING_SERVICE] Received presigned URL request:")
        logger.info(f"  - Filename: {request_data.filename}")
        logger.info(f"  - MIME Type: {request_data.mime_type}")
        logger.info(f"  - Presigned URL: {request_data.presigned_url[:100]}...")
        
        logger.info(
            f"📄 Processing via URL: {request_data.filename} "
            f"(type: {request_data.mime_type}, timeout={settings.docling_processing_timeout_seconds}s)"
        )
        logger.info(f"🔗 Full presigned URL: {request_data.presigned_url}")
        
        # Get processor
        processor = await get_processor()
        logger.info(f"� [DOCLING_SERVICE] Got processor: {type(processor)}")
        
        # Process document directly from presigned URL (no temp file needed)
        logger.info(f"� [DOCLING_SERVICE] Starting docling processing from presigned URL...")
        markdown_content, metadata = await processor.process_document_from_url(
            presigned_url=request_data.presigned_url,
            original_filename=request_data.filename,
            mime_type=request_data.mime_type,
            timeout_seconds=settings.docling_processing_timeout_seconds
        )
        
        logger.info(f"📊 [DOCLING_SERVICE] Processing result: markdown_content={bool(markdown_content)}, metadata_keys={list(metadata.keys()) if metadata else 'None'}")
        
        # Handle processing errors
        if not markdown_content:
            error_msg = metadata.get("error", "Unknown error")
            logger.warning(f"⚠️ Processing failed for {request_data.filename}: {error_msg}")
            raise HTTPException(
                status_code=422,
                detail=f"Conversion failed: {error_msg}"
            )
        
        logger.info(f"✅ Successfully processed: {request_data.filename}")
        
        return DoclingProcessResponse(
            success=True,
            content=markdown_content,
            metadata=metadata,
            error=None
        )
    
    except HTTPException as http_exc:
        logger.error(f"❌ HTTP Exception processing {request_data.filename}: {http_exc.status_code} - {http_exc.detail}")
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error processing {request_data.filename}: {e}")
        import traceback
        logger.error(f"🔍 Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected processing error: {str(e)}"
        )
    
    finally:
        # Cleanup temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp file {temp_file_path}: {e}")
        
        # Force garbage collection to free memory
        import gc
        gc.collect()
        logger.debug("🧹 Garbage collection completed")


@router.get("/health")
async def health_check(request: Request) -> dict:
    """Health check endpoint."""
    try:
        processor = await get_processor()
        health = await processor.health_check()

        return {
            "status": "healthy" if health["initialized"] else "degraded",
            "docling_initialized": health["initialized"],
            "ocr_initialized": health["converter_available"],
            "service": "docling-service",
            "model": settings.docling_model_name
        }
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return {
            "status": "unhealthy",
            "docling_initialized": False,
            "ocr_initialized": False,
            "service": "docling-service",
            "error": str(e)
        }
