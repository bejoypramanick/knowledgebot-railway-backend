import logging
import re
import uuid
from datetime import datetime
from typing import List, Annotated, Dict, Any, Optional

from google.genai import types

from services.chatbot_orchestration.core.ai import get_genai_client
from services.chatbot_orchestration.core.database import get_railway_db
from services.chatbot_orchestration.schemas.models import SearchResult
from shared.token_tracker import track_gemini_usage_from_response

logger = logging.getLogger(__name__)

async def search_knowledge_base(query: Annotated[str, "The search query to find relevant information in uploaded documents"]) -> List[SearchResult]:
    """
    Search the knowledge base using Gemini FileSearch for relevant information.

    This tool searches through uploaded documents and scraped content to find
    information relevant to the user's query.
    """
    logger.info(f"🔍 search_knowledge_base called with query: {query[:100]}...")
    genai_client = get_genai_client()
    if not genai_client:
        logger.warning("❌ Gemini API client not configured")
        return [SearchResult(
            file_name="System_Error",
            content="Gemini API client not configured - cannot search knowledge base",
            relevance_score=0.0,
            similarity_score=0.0,
            element_type="error",
            hierarchy_level=0,
            page_number=0
        )]

    try:
        logger.info("📂 Listing Gemini files...")
        # List all files in Gemini FileSearch
        # Convert generator to list
        try:
            all_files = list(genai_client.files.list())
            logger.info(f"📂 Found {len(all_files)} total files in Gemini FileSearch")
        except Exception as list_error:
            logger.error(f"❌ Failed to list Gemini files: {list_error}")
            all_files = []

        # Debug: Show file details for ALL files (even non-ACTIVE ones)
        if all_files:
            logger.info(f"📂 Showing details for all {len(all_files)} files:")
            for i, f in enumerate(all_files):
                state = getattr(f, 'state', None)
                state_name = state.name if hasattr(state, 'name') else str(state)
                logger.info(f"📄 File {i+1}: name='{f.name}', display_name='{getattr(f, 'display_name', 'N/A')}', state='{state_name}', mime_type='{getattr(f, 'mime_type', 'N/A')}'")
        else:
            logger.warning("⚠️ No files found in Gemini FileSearch - this prevents RAG usage tracking")
            logger.info("💡 This could mean: API rate limiting, files not uploaded, or authentication issues")

        # Filter for ACTIVE files only
        active_files = [f for f in all_files if getattr(f, 'state', None) and getattr(f.state, 'name', None) == "ACTIVE"]
        logger.info(f"📂 After filtering for ACTIVE files: {len(active_files)} active out of {len(all_files)} total")

        # Since user is on paid tier and files should exist, let's try a direct approach
        # Try to get files from database as backup
        try:
            from services.chatbot_orchestration.services.chat_service import chat_service
            db_files = await chat_service.get_recent_files(limit=5)
            if db_files:
                logger.info(f"📊 Found {len(db_files)} files in database that should be in Gemini:")
                for db_file in db_files:
                    logger.info(f"  • DB: {db_file['gemini_file_name']} -> {db_file['original_filename']} ({db_file['size_bytes']} bytes)")
                logger.warning("🔄 Files exist in DB but not found in Gemini API - possible sync issue")
            else:
                logger.info("📊 No files found in database either")
        except Exception as db_error:
            logger.error(f"Could not check database for files: {db_error}")
        
        if not all_files:
            logger.warning("No files found in FileSearch store")
            return []
            
        # Filter for ACTIVE files only
        active_files = [f for f in all_files if f.state.name == "ACTIVE"]

        if not active_files:
            logger.warning("No ACTIVE files found in FileSearch store")
            return []

        # Filter out files with unsupported MIME types for semantic search
        # Only allow the supported formats
        supported_mime_types = {
            # Documents
            'application/pdf',  # .pdf
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
            'text/plain',  # .txt
            # Spreadsheets
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
            'text/csv',  # .csv
            # Presentations
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # .pptx
            # Code
            'text/x-python',  # .py
            'application/javascript',  # .js
            'text/javascript',  # .js (alternative)
            'text/html',  # .html
            'application/json',  # .json
            'text/markdown',  # .md
        }

        # Filter files by supported MIME types
        supported_files = [f for f in active_files if getattr(f, 'mime_type', None) in supported_mime_types]

        if not supported_files:
            logger.warning("No files with supported MIME types found for semantic search")
            return []

        logger.info(f"Found {len(supported_files)} files with supported MIME types out of {len(active_files)} total ACTIVE files")

        # Sort by creation time (descending) to get the most recent files
        supported_files.sort(key=lambda f: f.create_time, reverse=True)

        # Use simple heuristic: take up to 5 most recent files to avoid payload limits
        files_to_search = supported_files[:5]
        
        logger.info(f"Searching {len(files_to_search)} files with Gemini 2.5 Flash Lite for query: {query}")

        try:
            # Helper function to extract original filename from display_name
            def extract_original_filename(display_name: str) -> str:
                """Extract original filename from display_name metadata format."""
                if ' | ' in display_name:
                    # Format: "Display Name | original_filename.ext"
                    parts = display_name.split(' | ', 1)
                    return parts[1].strip() if len(parts) > 1 else display_name
                else:
                    # No separator - display_name IS the original filename
                    return display_name
            
            # Create a mapping of file names to comprehensive metadata
            file_metadata_map = {}
            for f in files_to_search:
                display_name = getattr(f, 'display_name', f.name)
                original_filename = extract_original_filename(display_name)

                logger.debug(f"Processing Gemini file: name='{f.name}', display_name='{display_name}', extracted_original='{original_filename}'")

                # Try to get additional metadata from database
                db_metadata = {}
                try:
                    if chat_dao:
                        logger.debug(f"Attempting to fetch metadata for Gemini file: {f.name}, original_filename: {original_filename}")

                        # First try exact match with f.name
                        file_record = await chat_dao.find_file_by_name(f.name)

                        # If no exact match, try matching by original filename
                        if not file_record and original_filename:
                            logger.debug(f"No exact match for gemini_file_name '{f.name}', trying original_filename '{original_filename}'")
                            file_record = await chat_dao.find_file_by_original_name(original_filename)

                        # If still no match, try partial match on gemini_file_name
                        if not file_record:
                            filename_part = f.name.split('/')[-1] if '/' in f.name else f.name
                            logger.debug(f"Trying partial match with filename part: {filename_part}")
                            file_record = await chat_dao.find_file_by_partial_name(filename_part)

                        # As a last resort, try to find any file with similar name
                        if not file_record:
                            base_name = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename
                            logger.debug(f"Trying base name match: {base_name}")
                            file_record = await chat_dao.find_file_by_basename(base_name)

                        if file_record:
                            db_metadata = {
                                'document_id': str(file_record['id']),
                                'original_filename': file_record['original_filename'] or original_filename,
                                'display_name': file_record['display_name'] or display_name,
                                'mime_type': file_record['mime_type'],
                                'size_bytes': file_record['size_bytes'],
                                'upload_date': file_record['created_at'].isoformat() if file_record['created_at'] else None,
                                'db_metadata': file_record['metadata'] if isinstance(file_record['metadata'], dict) else {"raw": file_record['metadata']}
                            }
                            logger.info(f"Successfully retrieved database metadata for file {f.name}")
                        else:
                            logger.warning(f"No database record found for file {f.name} (original: {original_filename})")
                except Exception as e:
                    logger.error(f"Could not fetch file metadata from database: {e}")
                    # Don't import traceback in production unless needed, kept minimal

                file_metadata_map[f.name] = {
                    'display_name': display_name,
                    'original_filename': original_filename,
                    'document_id': db_metadata.get('document_id'),
                    's3_key': db_metadata.get('s3_key'),
                    'mime_type': db_metadata.get('mime_type'),
                    'size_bytes': db_metadata.get('size_bytes'),
                    'upload_date': db_metadata.get('upload_date'),
                    'db_metadata': db_metadata.get('db_metadata', {})
                }
            
            # Construct a simplified retrieval prompt
            retrieval_prompt = f"""
            You are a helpful AI assistant. Based on the user's query, provide relevant information that would be helpful for answering their question.

            User Query: "{query}"

            Instructions:
            1. Provide relevant information that could help answer this question.
            2. Focus on factual, helpful content.
            3. Keep your response concise and relevant.
            4. If you don't have specific information about this topic, provide general guidance.

            Output Format:
            Content: [Helpful information relevant to the user's query]
            """
            
            # Create cached content for RAG search prompt
            logger.info(f"🧠 Creating cached content for RAG search prompt...")
            try:
                cache = genai_client.caches.create(
                    model="gemini-2.5-flash-lite",
                    config=types.CreateCachedContentConfig(
                        display_name=f"rag_search_{query[:50]}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                        contents=[types.Part.from_text(retrieval_prompt)],
                        ttl="3600s"  # Cache for 1 hour
                    )
                )
                logger.info(f"✅ Created RAG search cached content: {cache.name}")
                
                # Use the cached content for the actual search (text-only for now)
                response = genai_client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=retrieval_prompt,
                    config=types.GenerateContentConfig(cached_content=cache.name)
                )
                logger.info(f"🔍 Gemini RAG search completed using cached content (text-only)")
            except Exception as cache_error:
                logger.warning(f"⚠️ Failed to create/use cached content: {cache_error}")
                logger.info("🔄 Falling back to direct Gemini API call for RAG search")
                
                # Simple text-only search without files
                response = genai_client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=retrieval_prompt
                )
                logger.info(f"🔍 Gemini RAG search completed (direct text-only call)")
            
            # Extract usage data from response for tracking
            usage_data = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage_data = response.usage_metadata
            elif hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'usage_metadata') and candidate.usage_metadata:
                        usage_data = candidate.usage_metadata
                        break

            if usage_data:
                try:
                    rag_session_id = str(uuid.uuid4())
                    await track_gemini_usage_from_response(usage_data, session_id=rag_session_id, api_call_type='rag')
                    logger.info("✅ Gemini usage tracking completed successfully")
                except Exception as tracking_error:
                    logger.error(f"❌ Failed to track Gemini usage: {tracking_error}")
            else:
                logger.warning(f"⚠️ Gemini RAG response missing usage data")

            # Parse the response to extract actual file names and clean content
            raw_response_text = response.text
            
            # Clean the response to extract only the relevant content
            def clean_gemini_response(response_text: str) -> str:
                """Clean Gemini response to extract only the relevant content."""
                lines = response_text.strip().split('\n')
                while lines and not lines[0].strip():
                    lines.pop(0)
                while lines and not lines[-1].strip():
                    lines.pop()

                content_lines = []
                found_content_marker = False

                for line in lines:
                    line = line.strip()
                    if not line: continue

                    if line.lower().startswith(('content:')):
                        found_content_marker = True
                        content_part = line[8:].strip()
                        if content_part:
                            content_lines.append(content_part)
                        continue
                    elif any(line.lower().startswith(prefix) for prefix in [
                        'user query:', 'instructions:', 'output format:', '- '
                    ]):
                        continue
                    elif found_content_marker or not any(line.lower().startswith(prefix) for prefix in [
                        'user query:', 'instructions:', 'output format:', 'you are a helpful ai assistant'
                    ]):
                        content_lines.append(line)

                content = ' '.join(content_lines)
                content = re.sub(r'\s+', ' ', content).strip()
                if len(content) < 10:
                    return response_text.strip()
                return content

            response_text = clean_gemini_response(raw_response_text)

            # Try to extract file name from response text
            source_file_pattern = r'Source File:\s*([^\n]+)'
            matches = re.finditer(source_file_pattern, raw_response_text, re.IGNORECASE)
            found_files = [match.group(1).strip() for match in matches]
            
            actual_file_name = None
            if found_files:
                found_name = found_files[0]
                for gemini_name, metadata in file_metadata_map.items():
                    display_name = metadata['display_name']
                    if found_name in display_name or display_name in found_name:
                        actual_file_name = metadata['original_filename']
                        break
                if not actual_file_name:
                    actual_file_name = extract_original_filename(found_name)
            
            # Fallback file name
            if not actual_file_name:
                if len(files_to_search) == 1:
                    first_file_metadata = file_metadata_map.get(files_to_search[0].name, {})
                    actual_file_name = first_file_metadata.get('original_filename', 
                        getattr(files_to_search[0], 'display_name', 'Unknown File'))
                else:
                    first_file_metadata = file_metadata_map.get(files_to_search[0].name, {})
                    actual_file_name = first_file_metadata.get('original_filename', 'Multiple Files')
            
            chunk_id = f"search_{uuid.uuid4().hex[:16]}"
            file_metadata = file_metadata_map.get(files_to_search[0].name, {}) if files_to_search else {}

            page_number = None
            page_match = re.search(r'Page\s*(\d+)', response_text[:200], re.IGNORECASE)
            if page_match:
                page_number = int(page_match.group(1))

            comprehensive_metadata = {
                "search_query": query,
                "files_searched": len(files_to_search),
                "gemini_model": "gemini-2.5-flash-lite",
                "search_method": "semantic_retrieval",
                "response_length": len(response_text),
                "extraction_timestamp": datetime.utcnow().isoformat(),
                "file_metadata": file_metadata
            }

            return [SearchResult(
                file_name=actual_file_name,
                content=response_text,
                relevance_score=1.0,
                similarity_score=1.0,
                chunk_id=chunk_id,
                document_id=file_metadata.get('document_id') or str(uuid.uuid4()),
                source="gemini_search",
                s3_key=file_metadata.get('s3_key'),
                original_filename=file_metadata.get('original_filename') or actual_file_name,
                page_number=page_number or 1,
                element_type="search_result",
                hierarchy_level=1,
                metadata=comprehensive_metadata
            )]
            
        except Exception as e:
            logger.error(f"Error in Neural Retrieval: {e}")
            return [SearchResult(
                file_name="System_Error",
                content=f"Error performing semantic search: {str(e)}",
                relevance_score=0.1,
                similarity_score=0.1,
                chunk_id=f"error_{uuid.uuid4().hex[:16]}",
                element_type="error",
                hierarchy_level=0,
                page_number=0,
                metadata={
                    "error_type": "search_failed",
                    "error_message": str(e)
                }
            )]
        
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}")
        return []
