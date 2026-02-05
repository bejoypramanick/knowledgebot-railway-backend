"""Docling Service API Router."""
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Request

from docling_service.core.docling_processor import get_processor
from docling_service.core.config import settings
from docling_service.schemas.models import DoclingProcessResponse
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
            return DoclingProcessResponse(
                success=False,
                content=None,
                metadata=metadata,
                error=error_msg
            )

        logger.info(f"✅ Successfully processed: {file.filename}")

        return DoclingProcessResponse(
            success=True,
            content=markdown_content,
            metadata=metadata,
            error=None
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unexpected error processing {file.filename}: {e}")
        return DoclingProcessResponse(
            success=False,
            content=None,
            metadata={"error": str(e)},
            error=str(e)
        )

    finally:
        # Cleanup temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"⚠️ Failed to cleanup temp file {temp_file_path}: {e}")


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
