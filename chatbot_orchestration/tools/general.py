import os
import logging
from typing import Annotated

import httpx

from ..core.dependencies import ChatSessionDeps
from ..service.file_service import FileService

logger = logging.getLogger(__name__)

# Tool for requesting human agent connection
async def request_human_agent_connection(
    deps: ChatSessionDeps,
    reason: Annotated[str, "Brief reason why the user wants to connect to a human agent (optional)"]
) -> str:
    """
    Request to connect the user to a human agent for personalized assistance.
    
    Use this tool when:
    - The user explicitly asks to speak with a human, real person, or agent
    - The user requests human support or assistance
    - The user is frustrated and needs human help
    - The query cannot be answered by the knowledge base or requires human judgment
    
    This will assign the chat to an available human agent and the chat will appear in their chat log.
    """
    session_id = deps.session_id
    
    try:
        # Get configuration service URL from environment
        config_service_url = os.getenv(
            'CONFIGURATION_SERVICE_URL',
            'https://configuration-service-production.up.railway.app'
        )
        
        # Call the request-human-agent endpoint
        headers = {}
        logger.info(f"Requesting human agent for session {session_id}")
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{config_service_url}/api/v1/chat/{session_id}/request-human-agent",
                json={},
                headers=headers
            )
            
            if response.status_code == 200:
                result = response.json()
                assigned_agent = result.get('assigned_agent', 'an agent')
                logger.info(f"Chat {session_id} assigned to human agent {assigned_agent}")
                return f"Successfully connected you to a human agent ({assigned_agent}). They will join the conversation shortly. The chat has been opened in their chat log."
            elif response.status_code == 503:
                error_detail = response.json().get('detail', 'No agents available')
                logger.warning(f"Human agent request failed: {error_detail}")
                return f"I'm sorry, but {error_detail.lower()}. Please try again later or continue chatting with me."
            else:
                error_detail = response.json().get('detail', 'Failed to connect to human agent')
                logger.error(f"Human agent request failed with status {response.status_code}: {error_detail}")
                return f"I encountered an error while trying to connect you to a human agent: {error_detail}. Please try again later."
                
    except httpx.TimeoutException:
        logger.error("Timeout while requesting human agent connection")
        return "The request to connect to a human agent timed out. Please try again."
    except Exception as e:
        logger.error(f"Error requesting human agent connection: {e}", exc_info=True)
        return f"I encountered an error while trying to connect you to a human agent. Please try again later."

async def query_railway_postgres(
    query: Annotated[str, "SQL-like query description or natural language question about file uploads, users, or metrics"]
) -> str:
    """
    Query Railway PostgreSQL database for file metadata, user information, or metrics.
    
    Use this for questions about:
    - Uploaded files and their metadata
    - User information (non-PII only)
    - System metrics and analytics
    - File upload history
    
    IMPORTANT: Never expose PII (personally identifiable information) like emails, names, or personal data.
    Only return aggregated statistics, file metadata, and anonymized information.
    """
    try:
        file_service = FileService()  # Service manages its own DAO
        
        # Parse the query and construct appropriate response
        query_lower = query.lower()
        
        # File-related queries
        if any(word in query_lower for word in ['file', 'upload', 'document', 'document']):
            if 'count' in query_lower or 'total' in query_lower or 'number' in query_lower:
                result = await file_service.get_active_files_count()
                return f"Total active files in the system: {result}"
            elif 'recent' in query_lower or 'latest' in query_lower:
                files = await file_service.get_recent_files(5)
                if files:
                    result = "Recent uploaded files:\n"
                    for f in files:
                        result += f"- {f['display_name']} ({f['mime_type']}, {f['size_bytes']} bytes, uploaded {f['uploaded_at']})\n"
                    return result
                return "No recent files found."
            else:
                # General file info
                files = await file_service.get_recent_files(10)
                if files:
                    result = f"Found {len(files)} active files:\n"
                    for f in files:
                        result += f"- {f['display_name']} ({f['mime_type']})\n"
                    return result
                return "No files found in the database."
        
        # Metrics queries
        elif any(word in query_lower for word in ['metric', 'statistic', 'analytics', 'usage']):
            metrics = await file_service.get_recent_metrics(10)
            if metrics:
                result = "Recent metrics (last 7 days):\n"
                for m in metrics:
                    result += f"- {m['metric_name']}: {m['total_value']} {m['unit'] or ''}\n"
                return result
            return "No metrics found."
        
        # Default: return file count
        count = await file_service.get_active_files_count()
        return f"Database contains {count} active files. Please be more specific about what information you need."
        
    except Exception as e:
        logger.error(f"Error querying Railway PostgreSQL: {e}")
        return f"Error querying database: {str(e)}"


