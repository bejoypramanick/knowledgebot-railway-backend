"""Core Docling document processing logic with image OCR extraction."""
import asyncio
import io
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

# Configure model cache directories BEFORE importing libraries
# This ensures models download to the persistent volume
os.environ.setdefault('HF_HOME', '/models/huggingface')
os.environ.setdefault('EASYOCR_USER_AGENT_ORIGIN', '/models/easyocr')

# Create cache directories if they don't exist
os.makedirs('/models/huggingface', exist_ok=True)
os.makedirs('/models/easyocr', exist_ok=True)
os.makedirs(os.path.expanduser('~/.EasyOCR'), exist_ok=True)

from docling.document_converter import DocumentConverter
from docling.models.document import ConvertedDocument
import easyocr

logger = logging.getLogger("docling_service")


class DoclingProcessor:
    """Handles document conversion to markdown using Docling with image OCR extraction."""

    def __init__(self, model_name: str = "granite-docling-258m"):
        """Initialize the Docling processor."""
        self.model_name = model_name
        self._converter: Optional[DocumentConverter] = None
        self._ocr_reader: Optional[easyocr.Reader] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Lazy initialize the DocumentConverter and OCR reader in async context.
        Returns True if successful, False otherwise.
        """
        if self._initialized:
            return True

        try:
            # Run converter and OCR initialization in thread pool (it's blocking)
            loop = asyncio.get_event_loop()

            # Initialize DocumentConverter
            self._converter = await loop.run_in_executor(
                None,
                self._init_converter
            )
            logger.info(f"✅ DocumentConverter initialized with model: {self.model_name}")

            # Initialize OCR Reader (supports multiple languages)
            self._ocr_reader = await loop.run_in_executor(
                None,
                self._init_ocr_reader
            )
            logger.info("✅ OCR Reader initialized for image text extraction")

            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Docling: {e}")
            return False

    def _init_converter(self) -> DocumentConverter:
        """Blocking initialization of DocumentConverter."""
        return DocumentConverter(model_name=self.model_name)

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

            # Extract markdown
            markdown_content = converted_doc.document_to_markdown()

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

    def _convert_document(self, file_path: str) -> ConvertedDocument:
        """
        Blocking document conversion.
        Called in thread pool executor.
        """
        if not self._converter:
            raise RuntimeError("Docling converter not initialized")

        source = Path(file_path)
        return self._converter.convert(source)

    async def _extract_and_ocr_images(
        self,
        converted_doc: ConvertedDocument,
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
