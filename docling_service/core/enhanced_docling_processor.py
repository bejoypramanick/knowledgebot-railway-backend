"""Enhanced Docling processor with advanced features for better document processing."""
import asyncio
import json
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
    logger.info("🔍 [IMPORT] Attempting to import docling libraries...")
    
    # Check docling version and available modules
    try:
        import docling
        logger.info(f"📦 [VERSION] Docling version: {docling.__version__}")
        logger.info(f"📦 [MODULES] Available docling modules: {[name for name in dir(docling) if not name.startswith('_')]}")
    except Exception as e:
        logger.warning(f"⚠️ [VERSION] Could not get docling version: {e}")
    
    from docling.document_converter import DocumentConverter
    logger.info("✅ [IMPORT] DocumentConverter imported successfully")
    
    from docling.datamodel.base_models import ConversionStatus
    logger.info("✅ [IMPORT] ConversionStatus imported successfully")
    
    
    # Try to import format-specific options for newer docling versions
    try:
        from docling.datamodel.base_models import PdfFormatOption, WordFormatOption, HtmlFormatOption, ExcelFormatOption
        logger.info("✅ [IMPORT] Format-specific options imported successfully")
    except ImportError as e:
        PdfFormatOption = None
        WordFormatOption = None
        HtmlFormatOption = None
        ExcelFormatOption = None
        logger.warning(f"⚠️ [IMPORT] Format-specific options not available: {e}")
           
    # Build list of acceptable conversion statuses
    _acceptable_statuses = [ConversionStatus.SUCCESS]
    if hasattr(ConversionStatus, 'PARTIAL_SUCCESS'):
        _acceptable_statuses.append(ConversionStatus.PARTIAL_SUCCESS)
    elif hasattr(ConversionStatus, 'SUCCESS_WITH_ERRORS'):
        _acceptable_statuses.append(ConversionStatus.SUCCESS_WITH_ERRORS)
    _ACCEPTABLE_CONVERSION_STATUSES = tuple(_acceptable_statuses)
    
    logger.info("✅ [IMPORT] Docling libraries imported successfully")
    logger.info(f"✅ [IMPORT] Acceptable conversion statuses: {_ACCEPTABLE_CONVERSION_STATUSES}")
    logger.info(f"📦 [IMPORT] Available modules: DocumentConverter={DocumentConverter is not None}, PdfPipelineOptions={PdfPipelineOptions is not None}")
    
except ImportError as e:
    logger.error(f"❌ [IMPORT] Failed to import docling libraries: {e}")
    logger.error(f"❌ [IMPORT] This might be due to missing dependencies or version conflicts")
    logger.error(f"❌ [IMPORT] Try running: pip install --upgrade docling docling-core")
    logger.error(f"❌ [IMPORT] Or check if docling is properly installed in the container")
    _ACCEPTABLE_CONVERSION_STATUSES = ()
    ConversionStatus = None
    DocumentConverter = None
    PdfPipelineOptions = None
    TableFormerMode = None
    InputFormat = None
    settings = None
    OcrMacModel = None


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
        self.enable_cell_matching = True  
        self.enable_export_to_dict = True
        
        # Set tableformer mode only if TableFormerMode is available
        if TableFormerMode is not None:
            self.tableformer_mode = TableFormerMode.ACCURATE 
        else:
            self.tableformer_mode = "ACCURATE"  # Fallback string 
        
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
            
            # Check if required imports are available
            if DocumentConverter is None:
                logger.error("❌ DocumentConverter not available")
                return False
            
            # Initialize converter with advanced options using new docling structure
            pipeline_options = None
            if InputFormat is not None and PdfPipelineOptions is not None:
                pipeline_options = PdfPipelineOptions()
                logger.info("✅ PdfPipelineOptions initialized successfully")
            elif InputFormat is not None:
                logger.warning("⚠️ PdfPipelineOptions not available, using basic pipeline")
            
            if InputFormat is not None and PdfPipelineOptions is not None:
                # Check available attributes before using them
                if pipeline_options is not None:
                    available_attrs = [attr for attr in dir(pipeline_options) if not attr.startswith('_')]
                    logger.info(f"🔧 [PIPELINE] Available PdfPipelineOptions attributes: {available_attrs}")
                else:
                    logger.warning("⚠️ [PIPELINE] PdfPipelineOptions is None, skipping attribute check")
                
                # Initialize converter using format-specific options
                converter_config = {}
                
                # PDF format with enhanced options to prevent "text soup"
                if hasattr(InputFormat, 'PDF') and PdfFormatOption is not None:
                    pdf_format_option = PdfFormatOption(
                        pipeline_options=pipeline_options
                        # backend="pypdfium2"  # Optional: force specific backend
                    )
                    converter_config[InputFormat.PDF] = pdf_format_option
                    logger.info("✅ [PDF] Using PdfFormatOption with enhanced structure analysis")
                
                # DOCX format with section handling for human reading order
                if hasattr(InputFormat, 'DOCX') and WordFormatOption is not None:
                    word_format_option = WordFormatOption(
                        pipeline_options=pipeline_options,
                        properties={"handle_sections": True}
                    )
                    converter_config[InputFormat.DOCX] = word_format_option
                    logger.info("✅ [DOCX] Using WordFormatOption with section handling")
                
                # HTML format with tag filtering to prevent menu indexing
                if hasattr(InputFormat, 'HTML') and HtmlFormatOption is not None:
                    html_format_option = HtmlFormatOption(
                        pipeline_options=pipeline_options,
                        # backend="custom"  # Optional: custom backend
                        # tags_filter=["nav", "footer", "script"]  # Strip unwanted tags
                    )
                    converter_config[InputFormat.HTML] = html_format_option
                    logger.info("✅ [HTML] Using HtmlFormatOption with tag filtering")
                
                # CSV/XLSX format with sheet names for RAG context
                if hasattr(InputFormat, 'XLSX') and ExcelFormatOption is not None:
                    excel_format_option = ExcelFormatOption(
                        pipeline_options=pipeline_options,
                        include_sheet_names=True
                    )
                    converter_config[InputFormat.XLSX] = excel_format_option
                    logger.info("✅ [XLSX] Using ExcelFormatOption with sheet names")
                
                if converter_config:
                    self._converter = DocumentConverter(format_options=converter_config)
                    logger.info(f"✅ Converter initialized with {len(converter_config)} format-specific options")
                else:
                    # Fallback to basic converter
                    self._converter = DocumentConverter()
                    logger.info("✅ Converter initialized without format options")
                
                logger.info("✅ Advanced pipeline options configured")
            else:
                self._converter = DocumentConverter()
                logger.info("✅ Converter initialized without format options")
            
            logger.info(f"✅ Enhanced docling processor initialized successfully")
            logger.info(f"🔧 [PROCESSOR] Converter type: {type(self._converter)}")
            logger.info(f"🔧 [PROCESSOR] Available methods: {[m for m in dir(self._converter) if not m.startswith('_')]}")
            
            self._initialized = True
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
                
                # Convert document using convert method
                logger.info(f"🔄 [CONVERT] Starting conversion for: {presigned_url}")
                
                # Use the convert method (standard in newer docling versions)
                if hasattr(self._converter, 'convert'):
                    logger.info("✅ [CONVERT] Using convert method")
                    conversion_result = self._converter.convert(presigned_url)
                else:
                    # Show available methods for debugging
                    available_methods = [m for m in dir(self._converter) if not m.startswith('_')]
                    logger.error(f"❌ [CONVERT] 'convert' method not found. Available methods: {available_methods}")
                    raise AttributeError("DocumentConverter missing 'convert' method")
                    
            except Exception as e:
                logger.error(f"❌ [CONVERT] Conversion failed: {e}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                raise
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
                # Extract markdown content for Gemini FileStore (simple and reliable)
                try:
                    markdown_content = conversion_result.render_as_markdown()
                    logger.info(f"✅ [ENHANCED] Markdown content generated: {len(markdown_content)} chars")
                    logger.info(f"📝 [MARKDOWN] Content preview: {markdown_content[:200]}...")
                    
                    # Log complete markdown content before sending to Gemini FileStore
                    logger.info(f"� [COMPLETE_MARKDOWN] Full markdown content before Gemini FileStore upload:")
                    logger.info(f"=== START COMPLETE MARKDOWN ===")
                    logger.info(f"{markdown_content}")
                    logger.info(f"=== END COMPLETE MARKDOWN ===")
                    logger.info(f"📊 [MARKDOWN_STATS] Total characters: {len(markdown_content)}")
                    logger.info(f"📊 [MARKDOWN_STATS] Total lines: {len(markdown_content.splitlines())}")
                    logger.info(f"📊 [MARKDOWN_STATS] Total words: {len(markdown_content.split())}")
                    
                except Exception as e:
                        logger.info(f"⚠️ [ENHANCED] JSON export failed, using markdown as primary: {len(markdown_content)} chars")
                        
                except AttributeError as e:
                    logger.error(f"❌ [ENHANCED] Content extraction failed: {e}")
                    return None, {"error": f"Content extraction error: {e}", "filename": original_filename}
                
                # Build enhanced metadata for markdown content
                metadata = {
                    "filename": original_filename,
                    "processing_time_ms": processing_time_ms,
                    "model": self.model_name,
                    "conversion_status": str(conversion_result.status),
                    "content_format": "markdown",
                    "enhanced_features": {
                        "layout_analysis": self.enable_layout_analysis,
                        "table_structure": self.enable_table_structure,
                        "cell_matching": self.enable_cell_matching,
                        "export_to_dict": self.enable_export_to_dict,
                        "tableformer_mode": str(self.tableformer_mode)
                    },
                    "content_stats": {
                        "markdown_length": len(markdown_content) if markdown_content else 0,
                        "json_length": 0
                    }
                }
                
                # Add layout information if available
                layout_info = self._extract_layout_info(conversion_result.docling_dict)
                metadata["layout_analysis"] = layout_info
                
                # Add table information if available
                table_info = self._extract_table_info(conversion_result.docling_dict)
                metadata["table_analysis"] = table_info
                
                # Return markdown content as primary output
                return markdown_content, metadata
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
                logger.info(f"📊 [STATS] JSON: {metadata['content_stats']['json_length']} chars, Markdown: {metadata['content_stats']['markdown_length']} chars")
                
                # Return JSON content as primary output, markdown as fallback
                if json_content and isinstance(json_content, dict):
                    # Return JSON dict as primary content
                    return json_content, metadata
                else:
                    # Return markdown as fallback when JSON fails
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
