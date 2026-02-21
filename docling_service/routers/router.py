"""Docling Service API Router - Presigned URL Only."""
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from docling_service.core.docling_processor import get_processor
from docling_service.core.config import settings
from docling_service.schemas.models import DoclingProcessResponse, DoclingProcessURLRequest
from docling_service.utils.validation import validate_file_for_processing
from docling_service.utils.constants import MAX_FILE_SIZE_BYTES

logger = logging.getLogger("docling_service")
router = APIRouter()


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
        logger.info(f"🔧 [ROUTER] Got processor: {type(processor)}")
        logger.info(f"🔧 [ROUTER] Processor initialized: {processor._initialized}")
        logger.info(f"🔧 [ROUTER] Processor model: {processor.model_name}")
        
        # Process document directly from presigned URL (no temp file needed)
        logger.info(f"📄 [ROUTER] Starting docling processing from presigned URL...")
        markdown_content, metadata = await processor.process_document_from_url(
            presigned_url=request_data.presigned_url,
            original_filename=request_data.filename,
            mime_type=request_data.mime_type
        )
        
        logger.info(f"📊 [ROUTER] Processing result: markdown_content={bool(markdown_content)}, metadata_keys={list(metadata.keys()) if metadata else 'None'}")
        logger.info(f"🔧 [ROUTER] Processing time: {metadata.get('processing_time_ms', 'N/A')}ms")
        logger.info(f"🔧 [ROUTER] Conversion status: {metadata.get('conversion_status', 'N/A')}")
        
        # Handle processing errors
        if not markdown_content:
            error_msg = metadata.get("error", "Unknown error")
            logger.warning(f"⚠️ [ROUTER] Processing failed for {request_data.filename}: {error_msg}")
            raise HTTPException(
                status_code=422,
                detail=f"Conversion failed: {error_msg}"
            )
        
        logger.info(f"✅ [ROUTER] Successfully processed: {request_data.filename}")
        
        return DoclingProcessResponse(
            success=True,
            content=markdown_content,
            metadata=metadata,
            error=None
        )
        
    except HTTPException as http_exc:
        logger.error(f"❌ [ROUTER] HTTP Exception processing {request_data.filename}: {http_exc.status_code} - {http_exc.detail}")
        return DoclingProcessResponse(
            success=False,
            content=None,
            metadata={"error": f"HTTP Exception: {http_exc.status_code} - {http_exc.detail}"},
            error=f"HTTP Exception: {http_exc.status_code} - {http_exc.detail}"
        )
        
    except Exception as e:
        logger.error(f"❌ [ROUTER] Unexpected error processing {request_data.filename}: {e}")
        import traceback
        logger.error(f"🔍 [ROUTER] Full traceback: {traceback.format_exc()}")
        return DoclingProcessResponse(
            success=False,
            content=None,
            metadata={"error": f"Unexpected error: {str(e)}"},
            error=f"Unexpected error: {str(e)}"
        )


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
            "model": processor.model_name if processor else None
        }
    except Exception as e:
        logger.error(f"❌ [ROUTER] Health check failed: {e}")
        return {
            "status": "unhealthy",
            "docling_initialized": False,
            "ocr_initialized": False,
            "service": "docling-service",
            "model": None,
            "error": str(e)
        }
