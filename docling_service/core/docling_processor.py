"""Simplified Docling processor for presigned URL processing only."""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("docling_service")

# Configure model cache directories BEFORE importing libraries
os.environ.setdefault('HF_HOME', '/models/huggingface')
os.environ.setdefault('EASYOCR_USER_AGENT_ORIGIN', '/models/easyocr')

# Create cache directories if they don't exist
try:
    os.makedirs('/models/huggingface', exist_ok=True)
    os.makedirs('/models/easyocr', exist_ok=True)
    os.makedirs(os.path.expanduser('~/.EasyOCR'), exist_ok=True)
    logger.info("✅ Cache directories created/verified")
except Exception as e:
    logger.warning(f"⚠️ Could not create cache directories: {e}")

# Import docling libraries
try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.base_models import ConversionStatus
    
    # Build list of acceptable conversion statuses
    _acceptable_statuses = [ConversionStatus.SUCCESS]
    if hasattr(ConversionStatus, 'PARTIAL_SUCCESS'):
        _acceptable_statuses.append(ConversionStatus.PARTIAL_SUCCESS)
    elif hasattr(ConversionStatus, 'SUCCESS_WITH_ERRORS'):
        _acceptable_statuses.append(ConversionStatus.SUCCESS_WITH_ERRORS)
    _ACCEPTABLE_CONVERSION_STATUSES = tuple(_acceptable_statuses)
    
    logger.info("✅ Docling libraries imported successfully")
    logger.info(f"✅ Acceptable conversion statuses: {_ACCEPTABLE_CONVERSION_STATUSES}")
    
except ImportError as e:
    logger.error(f"❌ Failed to import docling libraries: {e}")
    _ACCEPTABLE_CONVERSION_STATUSES = ()
    ConversionStatus = None
    DocumentConverter = None


class SimpleDoclingProcessor:
    """Simplified docling processor for presigned URL processing only."""
    
    def __init__(self, model_name: str = "granite-docling-258m"):
        """Initialize the simplified docling processor."""
        self.model_name = model_name
        self._converter = None
        self._initialized = False
        self._ocr_reader = None
        
    async def initialize(self) -> bool:
        """Initialize the docling processor."""
        try:
            logger.info(f"🔧 Initializing docling processor with model: {self.model_name}")
            
            # Initialize converter
            self._converter = DocumentConverter()
            
            self._initialized = True
            logger.info("✅ Docling processor initialized successfully")
            logger.info(f"🔧 [PROCESSOR] Converter type: {type(self._converter)}")
            logger.info(f"🔧 [PROCESSOR] Available methods: {[method for method in dir(self._converter) if not method.startswith('_')]}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize docling processor: {e}")
            return False
    
    async def process_document_from_url(
        self,
        presigned_url: str,
        original_filename: str,
        mime_type: str,
        timeout_seconds: int = 1800
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """Process a document from a presigned URL and return markdown content."""
        if not self._initialized:
            return None, {"error": "Docling processor not initialized"}
        
        try:
            logger.info(f"🔍 Starting conversion for URL: {presigned_url[:100]}...")
            
            # Suppress progress bar output by redirecting stdout/stderr
            import sys
            import io
            
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            
            try:
                # Redirect to null to suppress progress bars
                sys.stdout = io.StringIO()
                sys.stderr = io.StringIO()
                
                # Direct conversion from presigned URL
                conversion_result = self._converter.convert_single(presigned_url)
                
            finally:
                # Restore original stdout/stderr
                sys.stdout = original_stdout
                sys.stderr = original_stderr
            
            logger.info(f"🔍 Conversion completed, status: {conversion_result.status}")
            logger.info(f"🔧 [PROCESSOR] Conversion result type: {type(conversion_result)}")
            
            # Check if conversion was successful
            if conversion_result.status in _ACCEPTABLE_CONVERSION_STATUSES:
                # Extract markdown content - use the document property from ConversionResult
                try:
                    # Access the document from conversion result
                    docling_document = conversion_result.document
                    logger.info(f"🔧 [PROCESSOR] Got document object: {type(docling_document)}")
                    
                    # Try to export markdown from the document
                    markdown_content = docling_document.export_to_markdown()
                    logger.info(f"✅ [PROCESSOR] Document export worked, got {len(markdown_content) if markdown_content else 0} chars")
                except AttributeError as e:
                    logger.error(f"❌ [PROCESSOR] Document export failed: {e}")
                    logger.error(f"❌ [PROCESSOR] Presigned URL conversion unsuccessful for: {presigned_url}")
                    return None, {"error": f"Document export error: {e}", "filename": original_filename}
                
                # Build simple metadata
                metadata = {
                    "filename": original_filename,
                    "processing_time_ms": int(time.time() * 1000),  # Placeholder
                    "model": self.model_name,
                    "conversion_status": str(conversion_result.status)
                }
                
                logger.info(f"✅ Successfully processed: {original_filename}")
                return markdown_content, metadata
            else:
                error_msg = f"Conversion failed with status: {conversion_result.status}"
                logger.warning(f"⚠️ Processing failed for {original_filename}: {error_msg}")
                return None, {"error": error_msg}
                
        except Exception as e:
            logger.error(f"❌ Error processing {original_filename}: {e}")
            return None, {"error": str(e), "filename": original_filename}
    
    async def health_check(self) -> Dict[str, Any]:
        """Check docling processor health."""
        return {
            "initialized": self._initialized,
            "model": self.model_name,
            "converter_available": self._converter is not None
        }


# Global processor instance
_processor: Optional[SimpleDoclingProcessor] = None


async def get_processor() -> SimpleDoclingProcessor:
    """Get or create the global simplified docling processor."""
    global _processor
    if _processor is None:
        _processor = SimpleDoclingProcessor()
        await _processor.initialize()
    return _processor
