"""Enhanced Docling processor with advanced features for better document processing."""
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
    from docling.datamodel.base_models import ConversionStatus, InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.datamodel.settings import settings
    from docling.models.ocr_mac_model import OcrMacModel
    
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
    PdfPipelineOptions = None
    TableFormerMode = None
    InputFormat = None


class EnhancedDoclingProcessor:
    """Enhanced docling processor with advanced features for better document processing."""
    
    def __init__(self, model_name: str = "granite-docling-258m"):
        """Initialize the enhanced docling processor."""
        self.model_name = model_name
        self._converter = None
        self._initialized = False
        self._ocr_reader = None
        
        # Advanced processing options
        self.enable_layout_analysis = True
        self.enable_table_structure = True
        self.enable_cell_matching = False  # Use text cells from structure prediction
        self.enable_export_to_dict = True
        self.tableformer_mode = TableFormerMode.ACCURATE  # Use accurate mode for better quality
        
    async def initialize(self) -> bool:
        """Initialize the enhanced docling processor with advanced features."""
        try:
            logger.info(f"🔧 Initializing enhanced docling processor with model: {self.model_name}")
            logger.info(f"🔧 Advanced features:")
            logger.info(f"   - Layout Analysis: {self.enable_layout_analysis}")
            logger.info(f"   - Table Structure: {self.enable_table_structure}")
            logger.info(f"   - Cell Matching: {self.enable_cell_matching}")
            logger.info(f"   - Export to Dict: {self.enable_export_to_dict}")
            logger.info(f"   - TableFormer Mode: {self.tableformer_mode}")
            
            # Configure advanced pipeline options
            pipeline_options = PdfPipelineOptions()
            
            # Enable layout analysis for better document understanding
            if self.enable_layout_analysis:
                pipeline_options.do_layout_analysis = True
                logger.info("✅ Layout analysis enabled")
            
            # Enable table structure recognition
            if self.enable_table_structure:
                pipeline_options.do_table_structure = True
                pipeline_options.table_structure_options.do_cell_matching = self.enable_cell_matching
                pipeline_options.table_structure_options.mode = self.tableformer_mode
                logger.info(f"✅ Table structure enabled (cell_matching={self.enable_cell_matching}, mode={self.tableformer_mode})")
            
            # Enable OCR for scanned documents
            pipeline_options.do_ocr = True
            
            # Configure OCR settings
            if hasattr(settings, 'ocr'):
                settings.ocr.mac_model = OcrMacModel.MODEL_AUTO
                logger.info("✅ OCR auto-model selection enabled")
            
            # Initialize converter with advanced options
            self._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: pipeline_options
                }
            )
            
            self._initialized = True
            logger.info("✅ Enhanced docling processor initialized successfully")
            logger.info(f"🔧 [PROCESSOR] Converter type: {type(self._converter)}")
            logger.info(f"🔧 [PROCESSOR] Available methods: {[method for method in dir(self._converter) if not method.startswith('_')]}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize enhanced docling processor: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return False
    
    async def process_document_from_url(
        self,
        presigned_url: str,
        original_filename: str,
        mime_type: str,
        timeout_seconds: int = 1800
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        Process a document from a presigned URL with advanced features.
        Returns enhanced markdown content and detailed metadata.
        """
        if not self._initialized:
            return None, {"error": "Enhanced docling processor not initialized"}
        
        try:
            logger.info(f"🔍 Starting enhanced conversion for URL: {presigned_url[:100]}...")
            logger.info(f"📄 [ENHANCED] Processing with advanced features enabled")
            
            # Measure processing time
            conversion_start_time = time.time()
            
            # Suppress progress bar output by redirecting stdout/stderr
            import sys
            import io
            
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            
            try:
                # Redirect to null to suppress progress bars
                sys.stdout = io.StringIO()
                sys.stderr = io.StringIO()
                
                # Enhanced conversion from presigned URL
                conversion_result = self._converter.convert_single(presigned_url)
                
            finally:
                # Restore original stdout/stderr
                sys.stdout = original_stdout
                sys.stderr = original_stderr
            
            # Calculate actual processing time in milliseconds
            processing_time_ms = int((time.time() - conversion_start_time) * 1000)
            
            logger.info(f"🔍 Enhanced conversion completed, status: {conversion_result.status}")
            logger.info(f"🔧 [ENHANCED] Conversion result type: {type(conversion_result)}")
            logger.info(f"⏱️ [ENHANCED] Processing time: {processing_time_ms}ms")
            
            # Check if conversion was successful
            if conversion_result.status in _ACCEPTABLE_CONVERSION_STATUSES:
                # Extract enhanced content
                markdown_content = None
                docling_dict = None
                layout_info = {}
                table_info = {}
                
                try:
                    # Get markdown content
                    markdown_content = conversion_result.render_as_markdown()
                    logger.info(f"✅ [ENHANCED] render_as_markdown worked, got {len(markdown_content) if markdown_content else 0} chars")
                    
                    # Export to dict for structured data
                    if self.enable_export_to_dict:
                        docling_dict = conversion_result.document.export_to_dict()
                        logger.info(f"✅ [ENHANCED] Export to dict successful")
                        
                        # Extract layout information
                        if self.enable_layout_analysis and docling_dict:
                            layout_info = self._extract_layout_info(docling_dict)
                            logger.info(f"📐 [LAYOUT] Found {len(layout_info.get('elements', []))} layout elements")
                        
                        # Extract table information
                        if self.enable_table_structure and docling_dict:
                            table_info = self._extract_table_info(docling_dict)
                            logger.info(f"📊 [TABLES] Found {len(table_info.get('tables', []))} tables")
                    
                except AttributeError as e:
                    logger.error(f"❌ [ENHANCED] Content extraction failed: {e}")
                    return None, {"error": f"Content extraction error: {e}", "filename": original_filename}
                
                # Build enhanced metadata
                metadata = {
                    "filename": original_filename,
                    "processing_time_ms": processing_time_ms,
                    "model": self.model_name,
                    "conversion_status": str(conversion_result.status),
                    "enhanced_features": {
                        "layout_analysis": self.enable_layout_analysis,
                        "table_structure": self.enable_table_structure,
                        "cell_matching": self.enable_cell_matching,
                        "export_to_dict": self.enable_export_to_dict,
                        "tableformer_mode": str(self.tableformer_mode)
                    },
                    "content_stats": {
                        "markdown_length": len(markdown_content) if markdown_content else 0,
                        "word_count": len(markdown_content.split()) if markdown_content else 0,
                        "line_count": len(markdown_content.split('\n')) if markdown_content else 0
                    }
                }
                
                # Add layout information if available
                if layout_info:
                    metadata["layout_analysis"] = layout_info
                
                # Add table information if available
                if table_info:
                    metadata["table_analysis"] = table_info
                
                # Add structured data if available
                if docling_dict:
                    metadata["structured_data_available"] = True
                    # Store a summary of the structured data (not the full dict to avoid metadata bloat)
                    metadata["structured_summary"] = {
                        "total_pages": len(docling_dict.get('pages', [])),
                        "has_text_blocks": any('texts' in page for page in docling_dict.get('pages', [])),
                        "has_tables": any('tables' in page for page in docling_dict.get('pages', [])),
                        "has_images": any('pictures' in page for page in docling_dict.get('pages', []))
                    }
                
                logger.info(f"✅ Enhanced processing completed for: {original_filename}")
                logger.info(f"📊 [STATS] Content: {metadata['content_stats']['markdown_length']} chars, {metadata['content_stats']['word_count']} words")
                
                return markdown_content, metadata
            else:
                error_msg = f"Enhanced conversion failed with status: {conversion_result.status}"
                logger.warning(f"⚠️ Enhanced processing failed for {original_filename}: {error_msg}")
                return None, {"error": error_msg}
                
        except Exception as e:
            logger.error(f"❌ Error in enhanced processing {original_filename}: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return None, {"error": str(e), "filename": original_filename}
    
    def _extract_layout_info(self, docling_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Extract layout analysis information from docling document."""
        layout_info = {
            "elements": [],
            "total_elements": 0
        }
        
        try:
            pages = docling_dict.get('pages', [])
            for page_idx, page in enumerate(pages):
                # Extract text blocks
                texts = page.get('texts', [])
                for text in texts:
                    layout_info["elements"].append({
                        "type": "text",
                        "page": page_idx,
                        "content_length": len(text.get('text', '')),
                        "bbox": text.get('bbox', [])
                    })
                
                # Extract images/pictures
                pictures = page.get('pictures', [])
                for picture in pictures:
                    layout_info["elements"].append({
                        "type": "image",
                        "page": page_idx,
                        "bbox": picture.get('bbox', [])
                    })
            
            layout_info["total_elements"] = len(layout_info["elements"])
            
        except Exception as e:
            logger.warning(f"⚠️ Error extracting layout info: {e}")
        
        return layout_info
    
    def _extract_table_info(self, docling_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Extract table structure information from docling document."""
        table_info = {
            "tables": [],
            "total_tables": 0,
            "total_cells": 0
        }
        
        try:
            pages = docling_dict.get('pages', [])
            for page_idx, page in enumerate(pages):
                tables = page.get('tables', [])
                for table_idx, table in enumerate(tables):
                    cells = table.get('cells', [])
                    table_data = {
                        "page": page_idx,
                        "table_index": table_idx,
                        "rows": len(set(cell.get('row', []) for cell in cells)),
                        "cols": len(set(cell.get('col', []) for cell in cells)),
                        "cells_count": len(cells),
                        "bbox": table.get('bbox', [])
                    }
                    table_info["tables"].append(table_data)
                    table_info["total_cells"] += len(cells)
            
            table_info["total_tables"] = len(table_info["tables"])
            
        except Exception as e:
            logger.warning(f"⚠️ Error extracting table info: {e}")
        
        return table_info


# Create enhanced processor instance
enhanced_processor = EnhancedDoclingProcessor()
