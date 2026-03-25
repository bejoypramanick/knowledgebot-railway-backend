"""
Tables Metadata DAO - shared by file worker and web worker.
Inserts per-table metadata rows.
"""
import json
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("tables_metadata_dao", "shared")


async def save_tables_metadata(
    tables_metadata: List[Dict[str, Any]],
    file_upload_id: Optional[str] = None,
    scraped_website_id: Optional[str] = None
) -> bool:
    """
    Insert per-table metadata rows.

    Args:
        tables_metadata: List of dicts from process_extractor_content(), each with:
            table_index, table_column_count_input, table_row_count_input,
            table_character_count_input, table_word_count_input,
            table_word_count_output, table_character_count_output,
            table_input_token_count, table_output_token_count
        file_upload_id: FK to file_uploads (for file processing)
        scraped_website_id: FK to scraped_websites (for web processing)

    Returns: True on success, False on failure
    """
    if not tables_metadata:
        return True

    if not file_upload_id and not scraped_website_id:
        logger.warning("⚠️ [TABLES_META] No parent ID provided, skipping")
        return False

    parent_type = "file" if file_upload_id else "web"
    parent_id = file_upload_id or scraped_website_id
    logger.info(f"💾 [TABLES_META] Saving {len(tables_metadata)} table metadata records for {parent_type}={parent_id}")

    try:
        async with get_db_session() as session:
            # Insert individual table rows
            for meta in tables_metadata:
                await session.execute(
                    text("""
                        INSERT INTO tables_metadata (
                            file_upload_id, scraped_website_id, table_index,
                            table_column_count_input, table_row_count_input,
                            table_character_count_input, table_word_count_input,
                            table_word_count_output, table_character_count_output,
                            table_input_token_count, table_output_token_count
                        ) VALUES (
                            :file_upload_id, :scraped_website_id, :table_index,
                            :table_column_count_input, :table_row_count_input,
                            :table_character_count_input, :table_word_count_input,
                            :table_word_count_output, :table_character_count_output,
                            :table_input_token_count, :table_output_token_count
                        )
                    """),
                    {
                        "file_upload_id": file_upload_id,
                        "scraped_website_id": scraped_website_id,
                        "table_index": meta.get("table_index", 0),
                        "table_column_count_input": meta.get("table_column_count_input", 0),
                        "table_row_count_input": meta.get("table_row_count_input", 0),
                        "table_character_count_input": meta.get("table_character_count_input", 0),
                        "table_word_count_input": meta.get("table_word_count_input", 0),
                        "table_word_count_output": meta.get("table_word_count_output", 0),
                        "table_character_count_output": meta.get("table_character_count_output", 0),
                        "table_input_token_count": meta.get("table_input_token_count", 0),
                        "table_output_token_count": meta.get("table_output_token_count", 0),
                    }
                )

            await session.commit()
            logger.info(f"✅ [TABLES_META] Saved {len(tables_metadata)} table records for {parent_type}={parent_id}")
            return True

    except Exception as e:
        logger.error(f"❌ [TABLES_META] Failed to save table metadata: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
        return False
