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
    
    # Check what's available in base_models
    try:
        import docling.datamodel.base_models as base_models
        available_classes = [name for name in dir(base_models) if not name.startswith('_')]
        logger.info(f"📦 [BASE_MODELS] Available classes: {available_classes}")
    except Exception as e:
        logger.warning(f"⚠️ [BASE_MODELS] Could not list base_models: {e}")
    
    # Try to import InputFormat for latest docling version
    try:
        from docling.datamodel.base_models import InputFormat
        logger.info("✅ [IMPORT] InputFormat imported successfully")
    except ImportError as e:
        InputFormat = None
        logger.warning(f"⚠️ [IMPORT] InputFormat not available: {e}")
        # Try to use DocInputType as fallback for older versions
        try:
            from docling.datamodel.base_models import DocInputType
            InputFormat = DocInputType  # Use DocInputType as fallback
            logger.info("✅ [IMPORT] Using DocInputType as InputFormat fallback")
        except ImportError:
            logger.warning("⚠️ [IMPORT] DocInputType not available either")
    
    # Try to import pipeline options for latest docling version
    try:
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        logger.info("✅ [IMPORT] PdfPipelineOptions and TableFormerMode imported successfully")
    except ImportError as e:
        # Try to use available classes for older versions
        try:
            from docling.datamodel.base_models import PipelineOptions, TableStructureOptions
            PdfPipelineOptions = PipelineOptions
            logger.info("✅ [IMPORT] Using PipelineOptions from base_models")
            
            # Try to get TableStructureOptions for table configuration
            try:
                from docling.datamodel.base_models import TableStructureOptions
                logger.info("✅ [IMPORT] TableStructureOptions available")
            except ImportError:
                logger.warning("⚠️ [IMPORT] TableStructureOptions not available")
            
            # TableFormerMode not available in this version
            TableFormerMode = None
            logger.warning("⚠️ [IMPORT] TableFormerMode not available in this version")
        except ImportError as e2:
            PdfPipelineOptions = None
            TableFormerMode = None
            logger.warning(f"⚠️ [IMPORT] Pipeline options not available: {e2}")
    
    # Try to import PdfFormatOption for newer docling versions
    try:
        from docling.datamodel.base_models import PdfFormatOption
        logger.info("✅ [IMPORT] PdfFormatOption imported successfully")
    except ImportError as e:
        PdfFormatOption = None
        logger.warning(f"⚠️ [IMPORT] PdfFormatOption not available: {e}")
        # Try alternative import paths
        try:
            from docling.datamodel.base_models import FormatOption
            PdfFormatOption = FormatOption
            logger.info("✅ [IMPORT] Using FormatOption as PdfFormatOption fallback")
        except ImportError:
            logger.warning("⚠️ [IMPORT] FormatOption not available either")
    
    # Try to import settings and configure EasyOCR only
    try:
        from docling.datamodel.settings import settings
        logger.info("✅ [IMPORT] Settings imported successfully")
        
        # Configure EasyOCR for OCR processing
        try:
            import easyocr
            logger.info("✅ [IMPORT] EasyOCR imported successfully")
            # EasyOCR will be used for OCR processing
        except ImportError as e:
            logger.warning(f"⚠️ [IMPORT] EasyOCR not available: {e}")
            logger.warning("⚠️ [IMPORT] OCR processing will be limited")
            
    except ImportError as e:
        settings = None
        logger.warning(f"⚠️ [IMPORT] Settings not available: {e}")
        logger.warning("⚠️ [IMPORT] Using default OCR settings")
    
    # Build list of acceptable conversion statuses
    _acceptable_statuses = [ConversionStatus.SUCCESS]
    if hasattr(ConversionStatus, 'PARTIAL_SUCCESS'):
        _acceptable_statuses.append(ConversionStatus.PARTIAL_SUCCESS)
    elif hasattr(ConversionStatus, 'SUCCESS_WITH_ERRORS'):
        _acceptable_statuses.append(ConversionStatus.SUCCESS_WITH_ERRORS)
    _ACCEPTABLE_CONVERSION_STATUSES = tuple(_acceptable_statuses)
    
    logger.info("✅ [IMPORT] Docling libraries imported successfully")
    logger.info(f"✅ [IMPORT] Acceptable conversion statuses: {_ACCEPTABLE_CONVERSION_STATUSES}")
    logger.info(f"📦 [IMPORT] Available modules: DocumentConverter={DocumentConverter is not None}, PdfPipelineOptions={PdfPipelineOptions is not None}, InputFormat={InputFormat is not None}")
    
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
            if InputFormat is not None and PdfPipelineOptions is not None:
                # Check available attributes before using them
                available_attrs = [attr for attr in dir(pipeline_options) if not attr.startswith('_')]
                logger.info(f"🔧 [PIPELINE] Available PdfPipelineOptions attributes: {available_attrs}")
                
                # Enable layout analysis for better document understanding
                if self.enable_layout_analysis:
                    if hasattr(pipeline_options, 'do_layout'):
                        pipeline_options.do_layout = True
                        logger.info("✅ Layout analysis enabled (do_layout)")
                    elif hasattr(pipeline_options, 'layout_analysis'):
                        pipeline_options.layout_analysis = True
                        logger.info("✅ Layout analysis enabled (layout_analysis)")
                    else:
                        logger.warning("⚠️ Layout analysis attribute not found in PdfPipelineOptions")
                
                # Enable table structure recognition
                if self.enable_table_structure:
                    if hasattr(pipeline_options, 'do_table_structure'):
                        pipeline_options.do_table_structure = True
                        logger.info("✅ Table structure enabled (do_table_structure)")
                    elif hasattr(pipeline_options, 'table_structure'):
                        pipeline_options.table_structure = True
                        logger.info("✅ Table structure enabled (table_structure)")
                    else:
                        logger.warning("⚠️ Table structure attribute not found in PdfPipelineOptions")
                    
                    # Configure table structure options if available
                    if hasattr(pipeline_options, 'table_structure_options'):
                        if hasattr(pipeline_options.table_structure_options, 'do_cell_matching'):
                            pipeline_options.table_structure_options.do_cell_matching = self.enable_cell_matching
                            logger.info(f"✅ Cell matching enabled: {self.enable_cell_matching}")
                        
                        # Set tableformer mode only if it's a valid enum and attribute exists
                        if (hasattr(pipeline_options.table_structure_options, 'mode') and 
                            TableFormerMode is not None and 
                            hasattr(TableFormerMode, 'ACCURATE')):
                            pipeline_options.table_structure_options.mode = self.tableformer_mode
                            logger.info(f"✅ TableFormer mode set: {self.tableformer_mode}")
                        else:
                            logger.warning("⚠️ TableFormer mode not available, using default")
                
                # Enable OCR for scanned documents
                if hasattr(pipeline_options, 'do_ocr'):
                    pipeline_options.do_ocr = True
                    logger.info("✅ OCR enabled (do_ocr)")
                elif hasattr(pipeline_options, 'ocr_enabled'):
                    pipeline_options.ocr_enabled = True
                    logger.info("✅ OCR enabled (ocr_enabled)")
                
                # Initialize converter using new docling structure
                if PdfFormatOption is not None:
                    # Use PdfFormatOption wrapper for newer versions
                    try:
                        # Try to find PDF format in InputFormat
                        pdf_format = None
                        if hasattr(InputFormat, 'PDF'):
                            pdf_format = InputFormat.PDF
                        else:
                            # Case-insensitive search for PDF format
                            for attr in dir(InputFormat):
                                if attr.lower() == 'pdf':
                                    pdf_format = getattr(InputFormat, attr)
                                    break
                        
                        if pdf_format is not None:
                            # Create PdfFormatOption with pipeline options
                            pdf_format_option = PdfFormatOption(
                                pipeline_options=pipeline_options
                                # backend="pypdfium2"  # Optional: force specific backend
                            )
                            converter_config = {
                                pdf_format: pdf_format_option
                            }
                            self._converter = DocumentConverter(format_options=converter_config)
                            logger.info("✅ Converter initialized with PdfFormatOption wrapper")
                        else:
                            logger.warning("⚠️ PDF format not found, using default converter")
                            self._converter = DocumentConverter()
                    except Exception as e:
                        logger.error(f"❌ Failed to create PdfFormatOption: {e}")
                        self._converter = DocumentConverter()
                else:
                    # Fallback to old method for older versions
                    converter_config = {}
                    if hasattr(InputFormat, 'PDF'):
                        converter_config[InputFormat.PDF] = pipeline_options
                        self._converter = DocumentConverter(format_options=converter_config)
                        logger.info("✅ Converter initialized with legacy format options")
                    else:
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
                
                # Log available methods for debugging
                available_methods = [method for method in dir(self._converter) if not method.startswith('_')]
                logger.info(f"🔧 [CONVERTER] Available DocumentConverter methods: {available_methods}")
                
                # Convert document using available method
                if hasattr(self._converter, 'convert_single'):
                    conversion_result = self._converter.convert_single(presigned_url)
                    logger.info("✅ [CONVERTER] Using convert_single method")
                elif hasattr(self._converter, 'convert'):
                    conversion_result = self._converter.convert(presigned_url)
                    logger.info("✅ [CONVERTER] Using convert method")
                else:
                    # Try to find the correct conversion method
                    conversion_methods = [m for m in available_methods if 'convert' in m.lower()]
                    if conversion_methods:
                        method_name = conversion_methods[0]
                        logger.info(f"🔧 [CONVERTER] Using available method: {method_name}")
                        conversion_result = getattr(self._converter, method_name)(presigned_url)
                    else:
                        raise AttributeError("No conversion method found in DocumentConverter")
                
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
                # Extract content in JSON format for Gemini FileStore
                json_content = None
                docling_dict = None
                layout_info = {}
                table_info = {}
                
                try:
                    # Export to dict for structured JSON content (primary output)
                    if self.enable_export_to_dict:
                        docling_dict = conversion_result.document.export_to_dict()
                        logger.info(f"✅ [ENHANCED] Export to dict successful")
                        json_content = json.dumps(docling_dict, indent=2, ensure_ascii=False)
                        logger.info(f"✅ [ENHANCED] JSON content generated: {len(json_content)} chars")
                        
                        # Extract layout information
                        if self.enable_layout_analysis and docling_dict:
                            layout_info = self._extract_layout_info(docling_dict)
                            logger.info(f"📐 [LAYOUT] Found {len(layout_info.get('elements', []))} layout elements")
                        
                        # Extract table information
                        if self.enable_table_structure and docling_dict:
                            table_info = self._extract_table_info(docling_dict)
                            logger.info(f"📊 [TABLES] Found {len(table_info.get('tables', []))} tables")
                    
                    # Return JSON content as primary output
                    if json_content:
                        # JSON is the primary content, markdown is secondary
                        markdown_content = conversion_result.render_as_markdown()
                        logger.info(f"✅ [ENHANCED] JSON content generated: {len(json_content)} chars, markdown fallback: {len(markdown_content)} chars")
                    else:
                        # If JSON export fails, return empty dict and use markdown
                        json_content = {}
                        markdown_content = conversion_result.render_as_markdown()
                        logger.info(f"⚠️ [ENHANCED] JSON export failed, using markdown as primary: {len(markdown_content)} chars")
                        
                except AttributeError as e:
                    logger.error(f"❌ [ENHANCED] Content extraction failed: {e}")
                    return None, {"error": f"Content extraction error: {e}", "filename": original_filename}
                
                # Build enhanced metadata
                metadata = {
                    "filename": original_filename,
                    "processing_time_ms": processing_time_ms,
                    "model": self.model_name,
                    "conversion_status": str(conversion_result.status),
                    "content_format": "json" if (json_content and isinstance(json_content, dict)) else "markdown",
                    "enhanced_features": {
                        "layout_analysis": self.enable_layout_analysis,
                        "table_structure": self.enable_table_structure,
                        "cell_matching": self.enable_cell_matching,
                        "export_to_dict": self.enable_export_to_dict,
                        "tableformer_mode": str(self.tableformer_mode)
                    },
                    "content_stats": {
                        "json_length": len(json_content) if json_content else 0,
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
