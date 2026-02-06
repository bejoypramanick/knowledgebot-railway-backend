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

def extract_content_from_html(file_path: str = None, html_content: str = None) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Extract structured content from HTML using trafilatura.
    
    Args:
        file_path: Optional path to an HTML file
        html_content: Optional HTML content string
        
    Returns:
        Tuple of (markdown_content, metadata)
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
            include_images=False,
            include_formatting=False,
            include_links=False,
            output_format='markdown'
        )
        
        if not extracted:
            # Fallback to BeautifulSoup if trafilatura fails to find main content
            if BeautifulSoup:
                soup = BeautifulSoup(content, 'html.parser')
                # Explicitly remove noise elements
                for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    element.extract()
                extracted = soup.get_text(separator='\n', strip=True)
            else:
                return None, {"error": "Content extraction failed and BeautifulSoup not available"}
        
        metadata = {
            "success": True,
            "processor": "trafilatura",
            "content_length": len(extracted) if extracted else 0
        }
        
        return extracted, metadata
        
    except Exception as e:
        logger.error(f"❌ Error extracting HTML content: {e}")
        return None, {"error": str(e)}
