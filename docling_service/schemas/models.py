"""Pydantic models for Docling Service API."""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class DoclingProcessResponse(BaseModel):
    """Response model for document processing."""
    success: bool = Field(description="Whether processing was successful")
    content: Optional[str] = Field(None, description="Extracted markdown content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Processing metadata")
    error: Optional[str] = Field(None, description="Error message if processing failed")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "content": "# Document Title\n\nContent here...",
                "metadata": {
                    "filename": "document.pdf",
                    "processing_time_ms": 1500,
                    "model": "granite-docling-258m",
                    "markdown_length": 5000,
                    "document_pages": 10,
                    "images_extracted": 3,
                    "images_with_ocr": 3
                },
                "error": None
            }
        }


class HealthCheckResponse(BaseModel):
    """Response model for health check."""
    status: str = Field(description="Health status")
    docling_initialized: bool = Field(description="Whether Docling is initialized")
    ocr_initialized: bool = Field(description="Whether OCR is initialized")
    service: str = Field(default="docling-service", description="Service name")
