"""
HTML cleaning utilities for web extraction.
Designed to strip navigation/header/footer noise while preserving tables and images.
"""
import re
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def clean_html_preserving_images(html_content: str, url: Optional[str] = None) -> str:
    """
    Clean obvious navigation/footer/link noise before Kreuzberg extraction.

    We intentionally avoid Trafilatura extraction here because it can drop
    structured content like nested tables. Kreuzberg needs the rich HTML intact
    so tables, images, and surrounding context survive into downstream
    extraction. This cleaner therefore removes obvious boilerplate containers
    and strips low-value links while preserving content structure.
    """
    if not html_content:
        return ""

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, "lxml")
        removed = 0
        stripped_links = 0

        for tag_name in ("script", "noscript", "iframe", "template"):
            for element in soup.find_all(tag_name):
                element.decompose()
                removed += 1

        for selector in (
            "header",
            "footer",
            "nav",
            "[role='banner']",
            "[role='navigation']",
            "[role='contentinfo']",
        ):
            for element in soup.select(selector):
                element.decompose()
                removed += 1

        menu_pattern = re.compile(
            r"(^|[-_\s])(menu|nav|navbar|nav-bar|mega-menu|breadcrumb|breadcrumbs|footer|header|cookie|consent|banner|overlay|popover)($|[-_\s])",
            re.IGNORECASE,
        )
        for element in list(soup.find_all(True)):
            tokens = " ".join(
                str(value)
                for attr in ("id", "class", "role", "aria-label", "data-testid", "data-test")
                for value in (
                    element.get(attr, [])
                    if isinstance(element.get(attr), list)
                    else [element.get(attr)] if element.get(attr) else []
                )
            )
            if menu_pattern.search(tokens):
                element.decompose()
                removed += 1

        for anchor in soup.find_all("a"):
            href = (anchor.get("href") or "").strip()
            title = (anchor.get("title") or "").strip().lower()
            text_content = anchor.get_text(" ", strip=True)
            contains_only_image = not text_content and anchor.find("img") is not None
            is_junk_link = (
                not href
                or href.startswith("#cite_note")
                or "wikidata.org" in href
                or title == "edit this on wikidata"
            )

            anchor.attrs.pop("href", None)
            anchor.attrs.pop("title", None)

            if is_junk_link and contains_only_image:
                anchor.decompose()
            elif is_junk_link:
                anchor.unwrap()
            elif text_content or any(str(child).strip() for child in anchor.children):
                anchor.unwrap()
            else:
                anchor.decompose()
            stripped_links += 1

        logger.info(
            f"✅ [HTML_CLEAN] Removed navigation/footer/link noise without touching tables"
            f" | url={url or 'none'}"
            f" | removed_elements={removed}"
            f" | stripped_links={stripped_links}"
            f" | input_chars={len(html_content)}"
            f" | output_chars={len(str(soup))}"
        )
        return str(soup)
    except Exception as e:
        logger.warning(
            f"⚠️ [HTML_CLEAN] Navigation/link cleanup failed; using raw HTML"
            f" | url={url or 'none'}"
            f" | error={e}"
        )
        return html_content
