"""
Extract mathematical equations from PDF as images and use Gemini Vision
to accurately read them (avoiding extractor OCR errors).
"""
import json
import asyncio
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from core.ai import get_genai_client
from shared.otel_logger import get_otel_logger
from shared.usage_tracking import binary_payload_stats, text_payload_stats, track_model_usage

logger = get_otel_logger("equation_extractor", "extractor")


async def extract_and_fix_equations_with_vision(
    kreuzberg_json: str,
    pdf_images: Optional[List[bytes]] = None
) -> str:
    """
    Use Gemini Vision to read equations directly from images,
    avoiding docling's OCR character recognition errors.

    If no images provided, attempts to extract from docling's image data.

    Args:
        kreuzberg_json: Raw kreuzberg JSON output
        pdf_images: Optional list of page images (bytes) from PDF

    Returns:
        Text with equations corrected using Gemini Vision OCR
    """
    logger.info("[EQUATIONS_VISION] Starting equation extraction via Gemini Vision...")

    try:
        # Parse Kreuzberg JSON to find equation regions
        doc = json.loads(kreuzberg_json)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[EQUATIONS_VISION] Could not parse Kreuzberg JSON")
        return ""

    # Check if extractor has extracted images with bounding boxes
    pictures = doc.get("pictures", [])
    if not pictures:
        logger.info("[EQUATIONS_VISION] No pictures/images found in extractor output")
        return ""

    logger.info(f"[EQUATIONS_VISION] Found {len(pictures)} images in extractor output")

    try:
        genai_client = get_genai_client()
        if not genai_client:
            logger.warning("[EQUATIONS_VISION] Gemini client not available")
            return ""

        # For each image, ask Gemini to extract text and equations
        extracted_equations = {}

        for idx, picture in enumerate(pictures):
            # Get image data from docling
            image_content = picture.get("image")
            if not image_content:
                logger.warning(f"[EQUATIONS_VISION] Picture {idx} has no image data")
                continue

            # Convert base64 or bytes to format Gemini accepts
            # Assuming docling provides base64 encoded image
            if isinstance(image_content, str):
                # It's base64 encoded
                import base64
                try:
                    image_bytes = base64.b64decode(image_content)
                except Exception as e:
                    logger.warning(f"[EQUATIONS_VISION] Could not decode image {idx}: {e}")
                    continue
            else:
                image_bytes = image_content

            logger.info(f"[EQUATIONS_VISION] Processing image {idx+1}/{len(pictures)}...")

            prompt = """Analyze this image and extract ALL mathematical equations and formulas.

For each equation found:
1. Identify it clearly
2. Convert to proper LaTeX format
3. Include context (what is around the equation)
4. Correct any OCR errors (look for misread Greek letters, symbols, etc.)

Return in this format:
### Equation [number]
**Location/Context**: [Where in image, what is nearby]
**LaTeX**: [Properly formatted equation in LaTeX]
**Description**: [What this equation represents]

If you see incorrectly recognized characters (like f instead of φ, | instead of l, etc.),
correct them based on mathematical context."""

            loop = asyncio.get_event_loop()
            executor = ThreadPoolExecutor(max_workers=1)

            def call_gemini_vision():
                return genai_client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=[
                        prompt,
                        {
                            "inline_data": {
                                "mime_type": "image/png",  # Assuming PNG, adjust if needed
                                "data": image_bytes
                            }
                        }
                    ]
                )

            response = await loop.run_in_executor(executor, call_gemini_vision)
            try:
                usage = getattr(response, "usage_metadata", None) if response else None
                prompt_tokens = (
                    getattr(usage, "prompt_token_count", 0)
                    or getattr(usage, "promptTokenCount", 0)
                    or 0
                )
                completion_tokens = (
                    getattr(usage, "candidates_token_count", 0)
                    or getattr(usage, "candidatesTokenCount", 0)
                    or 0
                )
                total_tokens = (
                    getattr(usage, "total_token_count", 0)
                    or getattr(usage, "totalTokenCount", 0)
                    or (prompt_tokens + completion_tokens)
                )
                await track_model_usage(
                    provider="gemini",
                    model="gemini-1.5-flash",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    api_call_type="equation_vision",
                    request_metadata={
                        "image_index": idx,
                        "image_count": len(pictures),
                        "image_size_bytes": len(image_bytes or b""),
                        "mime_type": "image/png",
                        "token_source": "gemini_usage_metadata" if usage else "unavailable_gemini_usage_metadata",
                        **text_payload_stats(prompt),
                        **binary_payload_stats(image_bytes or b"", prefix="image"),
                    },
                )
            except Exception as usage_error:
                logger.warning(f"⚠️ [EQUATIONS_VISION] Failed to track usage for image {idx+1}: {usage_error}")

            if response and response.text:
                logger.info(f"✅ [EQUATIONS_VISION] Extracted equations from image {idx+1}")
                extracted_equations[f"image_{idx}"] = response.text
            else:
                logger.warning(f"⚠️ [EQUATIONS_VISION] No response for image {idx+1}")

        # Compile all extracted equations
        if extracted_equations:
            result = "## Extracted Equations (via Gemini Vision OCR)\n\n"
            for img_id, equations in extracted_equations.items():
                result += equations + "\n\n"

            logger.info(f"✅ [EQUATIONS_VISION] Extracted equations from {len(extracted_equations)} images")
            return result
        else:
            logger.warning("[EQUATIONS_VISION] No equations extracted from any images")
            return ""

    except Exception as e:
        logger.error(f"❌ [EQUATIONS_VISION] Error extracting equations: {e}")
        import traceback
        logger.error(f"[EQUATIONS_VISION] Traceback: {traceback.format_exc()}")
        return ""


def identify_equation_regions(kreuzberg_json: str) -> List[Dict[str, Any]]:
    """
    Identify regions in extractor output that likely contain equations.

    Looks for:
    - Text with mathematical symbols
    - Special bounding boxes marked as equations
    - Regions with suspected OCR errors

    Args:
        kreuzberg_json: Raw kreuzberg JSON

    Returns:
        List of suspected equation regions
    """
    try:
        doc = json.loads(kreuzberg_json)
    except (json.JSONDecodeError, TypeError):
        return []

    equation_regions = []
    texts = doc.get("texts", [])

    # Common indicators of equations (even if corrupted)
    math_indicators = [
        "∑", "∫", "√", "π", "φ", "α", "β", "γ", "∂", "∇",  # Greek/math symbols
        "^2", "^3", "**2", "**3",  # Powers
        "=/", "/=", "!=",  # Operators
        "x,", "y,", "z,",  # Variables
        "(",  # Parentheses indicating formulas
    ]

    for idx, text in enumerate(texts):
        text_content = text.get("text", "").strip()

        # Check for math indicators
        if any(indicator in text_content for indicator in math_indicators):
            equation_regions.append({
                "index": idx,
                "text": text_content,
                "bbox": text.get("bbox"),
                "label": text.get("label")
            })

    logger.info(f"[EQUATIONS] Identified {len(equation_regions)} suspected equation regions")
    return equation_regions
