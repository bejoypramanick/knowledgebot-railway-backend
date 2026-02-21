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

def extract_content_from_html(file_path: str = None, html_content: str = None, output_format: str = "markdown", remove_ads: bool = False) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Extract structured content from HTML using trafilatura.
    Supports both markdown and JSON output formats.
    
    Args:
        file_path: Optional path to an HTML file
        html_content: Optional HTML content string
        output_format: Output format - "markdown" or "json"
        remove_ads: Whether to remove advertising content
    
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
            
            # Remove advertising content if requested
            if remove_ads and 'structure' in content_dict:
                content_dict = _removeAdvertisingContent(content_dict)
            
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
                "structure": content_dict.get("structure", {}),
                "metadata": {
                    "processor": "trafilatura",
                    "extraction_time": time.time(),
                    "source_format": "html",
                    "output_format": "json",
                    "ads_removed": remove_ads
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
            "has_structured_data": bool(extracted and hasattr(extracted, 'as_dict')) if output_format == 'json' else False,
            "ads_removed": remove_ads
        }
        
        return content, metadata
        
    except Exception as e:
        logger.error(f"❌ Error extracting HTML content: {e}")
        return None, {"error": str(e)}

def _removeAdvertisingContent(content_dict: dict) -> dict:
    """Remove advertising-related content from the structure dictionary"""
    if 'structure' not in content_dict:
        return content_dict
    
    structure = content_dict['structure']
    
    # Remove advertising images
    if 'images' in structure:
        structure['images'] = [
            img for img in structure['images'] 
            if not _isAdvertisement(img.get('alt', ''))
        ]
    
    # Remove advertising links
    if 'links' in structure:
        structure['links'] = [
            link for link in structure['links'] 
            if not _isAdvertisementLink(link.get('href', ''))
        ]
    
    # Remove advertising tables
    if 'tables' in structure:
        structure['tables'] = [
            table for table in structure['tables']
            if not _isAdvertisementTable(table)
        ]
    
    # Remove scripts and forms related to advertising
    if 'scripts' in structure:
        structure['scripts'] = [
            script for script in structure['scripts']
            if not _isAdvertisementScript(script)
        ]
    
    if 'forms' in structure:
        structure['forms'] = [
            form for form in structure['forms']
            if not _isAdvertisementForm(form)
        ]
    
    return content_dict

def _isAdvertisement(alt_text: str) -> bool:
    """Detect if an image is likely an advertisement based on alt text"""
    if not alt_text:
        return False
    
    ad_keywords = ['ad', 'advertisement', 'banner', 'promo', 'sponsor', 'commercial']
    alt_lower = alt_text.lower()
    
    return any(keyword in alt_lower for keyword in ad_keywords)

def _isAdvertisementLink(href: str) -> bool:
    """Detect if a link is likely an advertisement"""
    if not href:
        return False
    
    ad_patterns = [
        'doubleclick.net', 'googleadservices.com', 'adsystem.com',
        'googlesyndication.com', 'facebook.com/tr', 'amazon-adsystem.com'
    ]
    
    href_lower = href.lower()
    return any(pattern in href_lower for pattern in ad_patterns)

def _isAdvertisementTable(table: dict) -> bool:
    """Detect if a table is likely an advertisement"""
    # Check for common ad table indicators
    table_text = ' '.join([
        str(cell.get('text', '')) for row in table.get('cells', [])
    ]).lower()
    
    ad_indicators = ['advertisement', 'sponsored', 'promo', 'banner ad']
    return any(indicator in table_text for indicator in ad_indicators)

def _isAdvertisementScript(script: dict) -> bool:
    """Detect if a script is related to advertising"""
    if isinstance(script, dict) and 'src' in script:
        src = script['src'].lower()
        ad_patterns = [
            'google-analytics', 'googletagmanager', 'facebook-pixel',
            'doubleclick', 'adsystem', 'googlesyndication'
        ]
        return any(pattern in src for pattern in ad_patterns)
    return False

def _isAdvertisementForm(form: dict) -> bool:
    """Detect if a form is related to advertising"""
    if isinstance(form, dict) and 'action' in form:
        action = form['action'].lower()
        ad_actions = ['subscribe', 'signup', 'newsletter', 'promotion']
        return any(action_item in action for action_item in ad_actions)
    return False
