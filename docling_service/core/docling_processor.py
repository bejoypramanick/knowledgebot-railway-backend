"""Core Docling document processing logic with image OCR extraction."""
import asyncio
import io
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger("docling_service")

# Configure model cache directories BEFORE importing libraries
# This ensures models download to the persistent volume
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

    # Log Docling version for diagnostics
    try:
        import docling
        logger.info(f"📦 Docling version: {docling.__version__}")
    except Exception as e:
        logger.warning(f"⚠️ Could not determine Docling version: {e}")

    # Build list of acceptable conversion statuses (handles version differences)
    # Docling 1.0.0-1.4.x use SUCCESS_WITH_ERRORS
    # Docling 1.5.0+ use PARTIAL_SUCCESS
    _acceptable_statuses = [ConversionStatus.SUCCESS]
    if hasattr(ConversionStatus, 'PARTIAL_SUCCESS'):
        _acceptable_statuses.append(ConversionStatus.PARTIAL_SUCCESS)
    elif hasattr(ConversionStatus, 'SUCCESS_WITH_ERRORS'):
        _acceptable_statuses.append(ConversionStatus.SUCCESS_WITH_ERRORS)
    _ACCEPTABLE_CONVERSION_STATUSES = tuple(_acceptable_statuses)

    logger.info("✅ Docling libraries imported successfully")
    logger.info(f"✅ Acceptable conversion statuses: {_ACCEPTABLE_CONVERSION_STATUSES}")
except ImportError as e:
    logger.error(f"❌ Failed to import docling: {e}")
    logger.error("Make sure docling is installed: pip install docling")
    raise

# Import easyocr
try:
    import easyocr
    logger.info("✅ EasyOCR library imported successfully")
except ImportError as e:
    logger.error(f"❌ Failed to import easyocr: {e}")
    logger.error("Make sure easyocr is installed: pip install easyocr")
    raise


class DoclingProcessor:
    """Handles document conversion to markdown using Docling with image OCR extraction."""
    
    def __init__(self, model_name: str = "granite-docling-258m"):
        """Initialize the Docling processor."""
        self.model_name = model_name
        self._converter: Optional[DocumentConverter] = None
        self._ocr_reader: Optional[easyocr.Reader] = None
        self._initialized = False
        
        # Cache for models and OCR readers to avoid re-downloads
        self._model_cache = {}
        self._ocr_cache = {}
        self._model_cache_dir = "/models/huggingface"
        self._ocr_cache_dir = "/models/easyocr"

    async def initialize(self) -> bool:
        """
        Lazy initialize the DocumentConverter and OCR reader in async context.
        Uses caching to avoid re-downloading models and OCR readers.
        Returns True if successful, False otherwise.
        """
        if self._initialized:
            return True
        
        try:
            loop = asyncio.get_event_loop()

            # Initialize DocumentConverter with caching
            if self.model_name not in self._model_cache:
                logger.info(f"📥 Downloading model: {self.model_name}")
                from docling.document_converter import DocumentConverter
                self._converter = await loop.run_in_executor(
                    None,
                    self._init_converter
                )
                self._model_cache[self.model_name] = self._converter
                logger.info(f"✅ DocumentConverter initialized with model: {self.model_name}")
            else:
                logger.info(f"📦 Using cached model: {self.model_name}")
                self._converter = self._model_cache[self.model_name]
            
            # Initialize OCR Reader with caching
            if 'easyocr' not in self._ocr_cache:
                logger.info(f"📥 Downloading EasyOCR")
                from easyocr import Reader
                self._ocr_reader = await loop.run_in_executor(
                    None,
                    self._init_ocr_reader
                )
                self._ocr_cache['easyocr'] = self._ocr_reader
                logger.info("✅ OCR Reader initialized")
            else:
                logger.info("📦 Using cached OCR Reader")
                self._ocr_reader = self._ocr_cache['easyocr']
            
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Docling: {e}")
            return False

    def _init_converter(self) -> DocumentConverter:
        """Blocking initialization of DocumentConverter."""
        return DocumentConverter()

    def _init_ocr_reader(self) -> easyocr.Reader:
        """Blocking initialization of EasyOCR Reader."""
        # Initialize with English language (can add more languages if needed)
        # Use GPU if available, otherwise CPU
        return easyocr.Reader(['en'], verbose=False, gpu=False)

    async def process_document(
        self,
        file_path: str,
        original_filename: str,
        timeout_seconds: int = 270
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Convert a document to markdown.

        Args:
            file_path: Path to the document file
            original_filename: Original filename for context
            timeout_seconds: Processing timeout in seconds

        Returns:
            Tuple of (markdown_content, metadata) or (None, {error: message}) on failure
        """
        if not self._initialized:
            return None, {"error": "Docling not initialized"}

        try:
            # Run conversion in thread pool with timeout
            loop = asyncio.get_event_loop()
            start_time = time.time()

            try:
                converted_doc = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._convert_document,
                        file_path
                    ),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                return None, {
                    "error": "Processing timeout",
                    "timeout_seconds": timeout_seconds,
                    "filename": original_filename
                }

            elapsed_time = time.time() - start_time

            # Extract markdown using docling 1.x API
            markdown_content = converted_doc.render_as_markdown()

            # Log the converted markdown content
            logger.info(
                f"📄 Converted Markdown for {original_filename} "
                f"({len(markdown_content)} chars):\n"
                f"{'='*80}\n"
                f"{markdown_content}\n"
                f"{'='*80}"
            )

            # Extract and OCR images from document
            image_ocr_results = await self._extract_and_ocr_images(
                converted_doc, original_filename
            )

            # Append image OCR results to markdown
            if image_ocr_results["images_found"] > 0:
                markdown_content += "\n\n## Extracted Image Text\n\n"
                markdown_content += image_ocr_results["ocr_markdown"]

            metadata = {
                "success": True,
                "processing_time_ms": int(elapsed_time * 1000),
                "filename": original_filename,
                "model": self.model_name,
                "markdown_length": len(markdown_content),
                "document_pages": len(list(converted_doc.pages)) if hasattr(converted_doc, 'pages') else 0,
                "images_extracted": image_ocr_results["images_found"],
                "images_with_ocr": image_ocr_results["ocr_count"]
            }

            logger.info(
                f"✅ Processed: {original_filename} "
                f"({metadata['processing_time_ms']}ms, "
                f"{len(markdown_content)} chars, "
                f"{metadata['images_with_ocr']} images OCR'd)"
            )

            return markdown_content, metadata

        except Exception as e:
            logger.error(f"❌ Error processing {original_filename}: {e}")
            return None, {
                "error": str(e),
                "filename": original_filename
            }

    def _convert_document(self, file_path: str) -> Any:
        """
        Blocking document conversion using docling convert_single() API.
        Called in thread pool executor.
        """
        if not self._converter:
            raise RuntimeError("Docling converter not initialized")

        try:
            logger.info(f"🔍 Starting conversion for: {file_path}")
            
            # Check file extension to determine processing approach
            file_ext = Path(file_path).suffix.lower()
            logger.info(f"� File extension detected: {file_ext}")
            
            # For HTML files, we need to handle them differently
            # HTML files should be processed directly by docling, not through convert_single
            if file_ext in ['.html', '.htm']:
                logger.info(f"🌐 Processing HTML file directly with docling")
                # Use docling's document processing directly for HTML
                from docling.document import load_document
                doc = load_document(file_path)
                conversion_result = doc.render_as_markdown()
                
                logger.info(f"🔍 HTML conversion completed, status: SUCCESS")
                return conversion_result
            else:
                # Use convert_single() for PDF and other supported formats
                logger.info(f"📄 Using convert_single() for file: {file_path}")
                conversion_result = self._converter.convert_single(file_path)
                logger.info(f"🔍 Conversion completed, status: {conversion_result.status}")

                # Check if conversion was successful
                if conversion_result.status not in _ACCEPTABLE_CONVERSION_STATUSES:
                    # Build error message with details from conversion result
                    error_msg = f"Conversion failed with status: {conversion_result.status}"
                    error_details = []

                    # Try to extract error details
                    if hasattr(conversion_result, 'errors') and conversion_result.errors:
                        try:
                            error_details = [str(e) if not hasattr(e, 'error_message') else e.error_message for e in conversion_result.errors]
                        except Exception as extract_error:
                            logger.warning(f"Failed to extract error details: {extract_error}")
                            error_details = [str(conversion_result.status)]

                    logger.error(f"🔍 {error_msg}")
                    raise RuntimeError(f"{error_msg}. Details: {error_details}")

                return conversion_result

        except Exception as e:
            logger.error(f"🔍 Error in _convert_document: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"🔍 Traceback: {traceback.format_exc()}")
            raise

    async def _extract_and_ocr_images(
        self,
        converted_doc: Any,
        filename: str
    ) -> Dict[str, Any]:
        """
        Extract images from document and perform OCR on them.

        Returns:
            Dict with images_found, ocr_count, and ocr_markdown
        """
        try:
            if not self._ocr_reader:
                return {
                    "images_found": 0,
                    "ocr_count": 0,
                    "ocr_markdown": ""
                }

            images_found = 0
            ocr_count = 0
            ocr_markdown = ""

            # Try to extract images from the document
            # Docling stores images in the document object
            if hasattr(converted_doc, '_pages'):
                for page_idx, page in enumerate(converted_doc._pages):
                    if hasattr(page, '_images'):
                        for img_idx, image_data in enumerate(page._images):
                            try:
                                images_found += 1

                                # Convert image to format suitable for OCR
                                image_bytes = io.BytesIO(image_data)
                                from PIL import Image
                                image = Image.open(image_bytes)

                                # Perform OCR
                                loop = asyncio.get_event_loop()
                                results = await loop.run_in_executor(
                                    None,
                                    self._ocr_reader.readtext,
                                    image
                                )

                                if results:
                                    ocr_count += 1
                                    extracted_text = "\n".join(
                                        [item[1] for item in results]
                                    )

                                    ocr_markdown += (
                                        f"\n### Image {page_idx + 1}.{img_idx + 1} OCR Text\n"
                                        f"{extracted_text}\n"
                                    )
                                else:
                                    logger.warning(
                                        f"⚠️ No OCR results for image {page_idx}.{img_idx} "
                                        f"in {filename}"
                                    )
                                    continue

                            except Exception as e:
                                logger.warning(
                                    f"⚠️ Failed to OCR image {page_idx}.{img_idx} "
                                    f"in {filename}: {e}"
                                )
                                continue

            return {
                "images_found": images_found,
                "ocr_count": ocr_count,
                "ocr_markdown": ocr_markdown
            }

        except Exception as e:
            logger.warning(f"⚠️ Error during image extraction/OCR: {e}")
            return {
                "images_found": 0,
                "ocr_count": 0,
                "ocr_markdown": ""
            }

    async def health_check(self) -> Dict[str, Any]:
        """Check Docling service health."""
        return {
            "initialized": self._initialized,
            "model": self.model_name,
            "converter_available": self._converter is not None
        }


# Global processor instance
_processor: Optional[DoclingProcessor] = None


async def get_processor() -> DoclingProcessor:
    """Get or create the global Docling processor."""
    global _processor
    if _processor is None:
        from docling_service.core.config import settings
        _processor = DoclingProcessor(model_name=settings.docling_model_name)
        await _processor.initialize()
    return _processor
