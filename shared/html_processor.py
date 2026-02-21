"""HTML processing utilities using trafilatura."""
import logging
import os
from typing import Optional, Tuple, Dict, Any

try:
    import trafilatura
    from bs4 import BeautifulSoup
except ImportError:
    trafilatura = None
    BeautifulSoup = None

logger = logging.getLogger("shared")

def extract_content_from_html(file_path: str = None, html_content: str = None, output_format: str = "markdown") -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Extract structured content from HTML using trafilatura.
    Supports both markdown and JSON output formats.
    
    Args:
        file_path: Optional path to an HTML file
        html_content: Optional HTML content string
        output_format: Output format - "markdown" or "json"
    
    Returns:
        Tuple of (content, metadata)
    """
    if trafilatura is None:
        return None, {"error": "trafilatura not installed"}
    
    try:
        content = html_content
        if file_path:
            if not os.path.exists(file_path):
                return None, {"error": "File not found"}
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        
        if content is None:
            return None, {"error": "No content provided"}
        
        # Extract main text using trafilatura (removes noise like nav, footer, ads)
        extracted = trafilatura.extract(
            content, 
            include_comments=False,
            include_tables=True,
            include_format=True,
            with_metadata=True,
            output_format='json' if output_format == 'json' else None
        )
        
        # Generate content based on output format
        if output_format == 'json' and extracted and hasattr(extracted, 'as_dict'):
            # Return structured JSON content
            content_dict = extracted.as_dict()
            
            # Create enhanced JSON structure
            json_content = {
                "content": {
                    "text": extracted.text or "",
                    "title": extracted.title or "",
                    "author": extracted.author or "",
                    "date": extracted.date or "",
                    "description": extracted.description or "",
                    "url": extracted.url or ""
                },
                "structure": {
                    "images": [{"src": img.get("src", ""), "alt": img.get("alt", "")} for img in (extracted.images or [])],
                    "links": [{"url": link.get("href", ""), "text": link.get("text", "")} for link in (extracted.links or [])],
                    "tables": extracted.tables or []
                },
                "metadata": {
                    "processor": "trafilatura",
                    "extraction_time": time.time(),
                    "source_format": "html",
                    "output_format": "json"
                }
            }
            
            # Convert to JSON string
            content = json.dumps(json_content, indent=2, ensure_ascii=False)
            logger.info(f"📋 [JSON_HTML] Generated JSON content: {len(content)} chars")
            
        else:
            # Fallback to BeautifulSoup if trafilatura fails or markdown requested
            if BeautifulSoup:
                soup = BeautifulSoup(content, 'html.parser')
                # Explicitly remove noise elements
                for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "button", "meta", "link", "noscript"]):
                    element.extract()
                
                # Get clean text
                clean_text = soup.get_text(separator=' ', strip=True)
                content = clean_text if output_format != 'json' else clean_text
                logger.info(f"📝 [MARKDOWN_HTML] Generated markdown content: {len(content)} chars")
        
        metadata = {
            "success": True,
            "processor": "trafilatura",
            "output_format": output_format,
            "content_length": len(extracted) if extracted else len(content),
            "has_structured_data": bool(extracted and hasattr(extracted, 'as_dict')) if output_format == 'json' else False
        }
        
        return content, metadata
        
    except Exception as e:
        logger.error(f"❌ Error extracting HTML content: {e}")
        return None, {"error": str(e)}
