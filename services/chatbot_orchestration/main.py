# --- 🔍 STARTUP DIAGNOSTIC ---
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Log port and environment basic state
logger.info("🔍 --- Chatbot Startup Diagnostics ---")
logger.info("🆔 SERVICE_IDENTITY: CHATBOT_ORCHESTRATION_V1")
logger.info(f"🐍 Python: {sys.version}")
logger.info(f"📂 Current Dir: {os.getcwd()}")
logger.info(f"🌐 CHATBOT_ORCH_PORT: {os.getenv('CHATBOT_ORCH_PORT')}")
logger.info(f"🌐 PORT (Railway): {os.getenv('PORT')}")
logger.info(f"🔍 ----------------------------------")

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    from typing import Optional, List, Dict, Any, Annotated
    from dataclasses import dataclass
    from dotenv import load_dotenv
    import uuid
    from datetime import datetime
    from google import genai
    from contextlib import asynccontextmanager
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart
    from pydantic_ai.models.openai import OpenAIModel
    import asyncio
    import json
    import re
    from pathlib import Path
    logger.info("✅ Core modules imported successfully")
except ImportError as e:
    logger.critical(f"💥 IMPORT ERROR: Could not load required module: {e}")
    # Print search path for debugging
    logger.info(f"📍 Python Path: {sys.path}")
    raise

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.config import settings
from shared.db import init_railway_db, init_neon_db, railway_db, neon_db
from shared.token_tracker import track_openai_usage_from_response, track_gemini_usage_from_response

# Lazy database initialization for serverless optimization
async def get_railway_db():
    """Get Railway database connection, initializing if needed."""
    global railway_db
    if railway_db is None and settings.railway_postgres_url:
        try:
            logger.info("🔄 Lazy initializing Railway PostgreSQL database...")
            railway_db = await init_railway_db(settings.railway_postgres_url)
            logger.info("✅ Railway PostgreSQL database initialized")

            # Debug: Show available files in database
            try:
                files_count = await railway_db.fetchval("SELECT COUNT(*) FROM file_uploads")
                logger.info(f"📊 Database contains {files_count} file records")

                if files_count > 0:
                    sample_files = await railway_db.fetch("""
                        SELECT gemini_file_name, original_filename, display_name
                        FROM file_uploads
                        ORDER BY created_at DESC
                        LIMIT 3
                    """)
                    logger.info("📋 Sample files in database:")
                    for sf in sample_files:
                        logger.info(f"   • Gemini: '{sf['gemini_file_name']}' | Original: '{sf['original_filename']}' | Display: '{sf['display_name']}'")
            except Exception as db_debug_e:
                logger.warning(f"Could not check database contents: {db_debug_e}")

        except Exception as e:
            logger.error(f"❌ Failed to initialize Railway PostgreSQL database: {e}")
            raise
    return railway_db

async def get_neon_db():
    """Get Neon database connection, initializing if needed."""
    global neon_db
    if neon_db is None and settings.neon_db_url:
        try:
            logger.info("🔄 Lazy initializing Neon database...")
            neon_db = await init_neon_db(settings.neon_db_url)
            logger.info("✅ Neon database initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Neon database: {e}")
            raise
    return neon_db

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure shared utilities are importable and enable global exception logging
import sys
from pathlib import Path
try:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
except Exception:
    logger.debug("Could not adjust sys.path for shared imports")

from shared.utils import setup_global_exception_logging, register_fastapi_exception_handlers, dependency_unavailable_error, log_system_metrics, log_endpoint_request
setup_global_exception_logging("chatbot_orchestration")

# Log status of required environment variables
if not settings.gemini_api_key:
    logger.error("❌ GEMINI_API_KEY is not configured - chat features will be unavailable")
if not settings.openai_api_key:
    logger.error("❌ OPENAI_API_KEY is not configured - chatbot service will fail to operate")

# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    logger.info("🔄 Chatbot orchestration lifespan starting...")

    # For serverless optimization: Skip heavy DB initialization during startup
    # Databases will be initialized lazily on first request to reduce cold start time
    logger.info("Chatbot orchestration service started successfully (lazy DB init)")
    logger.info(f"Health check endpoint: /health (Port: {os.getenv('PORT', '8003')})")
    yield

    # Shutdown - Close database connections if they exist
    logger.info("🛑 Shutting down chatbot orchestration service...")
    try:
        if railway_db and not railway_db.is_closed:
            await railway_db.disconnect()
            logger.info("✅ Railway PostgreSQL connection closed")
    except Exception as e:
        logger.warning(f"Error closing Railway DB: {e}")

    try:
        if neon_db and not neon_db.is_closed:
            await neon_db.disconnect()
            logger.info("✅ Neon DB connection closed")
    except Exception as e:
        logger.warning(f"Error closing Neon DB: {e}")

    logger.info("✅ Chatbot orchestration service shutdown complete")

app = FastAPI(
    title="Chatbot Orchestration Service",
    version="1.0.0",
    lifespan=lifespan
)

# Register FastAPI-level exception handlers to ensure stack traces are logged
register_fastapi_exception_handlers(app, "chatbot_orchestration")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize AI components (lazy initialization to avoid startup failures)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or settings.openai_api_key

# Global clients - initialized lazily
genai_client = None
openai_model = None

def get_genai_client():
    """Lazy initialization of Gemini client."""
    global genai_client
    if genai_client is None and GEMINI_API_KEY:
        try:
            genai_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("✅ Gemini client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
            genai_client = None
    return genai_client

def get_openai_model():
    """Lazy initialization of OpenAI model."""
    global openai_model
    if openai_model is None and OPENAI_API_KEY:
        try:
            openai_model = OpenAIModel(MODEL_NAME, api_key=OPENAI_API_KEY)
            logger.info("✅ OpenAI model initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize OpenAI model: {e}")
            openai_model = None
    return openai_model

MODEL_NAME = os.getenv("CHATBOT_MODEL", settings.chatbot_model)
TEMPERATURE = float(os.getenv("CHATBOT_TEMPERATURE", str(settings.chatbot_temperature)))
MAX_TOKENS = int(os.getenv("CHATBOT_MAX_TOKENS", str(settings.chatbot_max_tokens)))
logger.info(f"🤖 Model config: {MODEL_NAME}, temp={TEMPERATURE}, max_tokens={MAX_TOKENS}")

# Initialize Tavily for internet search (optional)
tavily_client = None
if settings.tavily_api_key and settings.enable_internet_search:
    try:
        from tavily import TavilyClient
        tavily_client = TavilyClient(api_key=settings.tavily_api_key)
        logger.info("✅ Tavily internet search initialized")
    except Exception as e:
        logger.warning(f"⚠️  Failed to initialize Tavily: {e}")
else:
    logger.info("ℹ️  Tavily not configured or disabled")

# In-memory session storage
sessions: Dict[str, Dict[str, Any]] = {}


# Pydantic models for structured outputs
class SearchResult(BaseModel):
    """Search result from Gemini FileSearch with comprehensive metadata."""
    # Original fields
    file_name: str
    content: str
    relevance_score: Optional[float] = None

    # Enhanced metadata fields to match frontend DocumentSource interface
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source: Optional[str] = None
    s3_key: Optional[str] = None
    original_filename: Optional[str] = None
    page_number: Optional[int] = None
    element_type: Optional[str] = None
    hierarchy_level: Optional[int] = None
    similarity_score: Optional[float] = None  # Alias for relevance_score
    metadata: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Structured chat response."""
    answer: str = Field(description="The answer to the user's question")
    sources: List[SearchResult] = Field(default_factory=list, description="Sources used for the answer")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score for the answer")
    data_sources_used: List[str] = Field(default_factory=list, description="Data sources used: rag, postgres, neon_db, internet")


class HumanReviewRequest(BaseModel):
    """Request for human review."""
    approved: bool
    feedback: Optional[str] = None
    corrected_answer: Optional[str] = None


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    max_results: int = 5
    system_prompt: Optional[str] = None  # Custom system prompt (will be appended to default)
    response_policy: Optional[int] = None  # 0-100: 0=flexible, 100=strict


class ChatSessionResponse(BaseModel):
    """Chat session response."""
    session_id: str
    message: str
    response: ChatResponse
    usage: Optional[Dict[str, Any]] = None
    timestamp: str


class SuggestedMessagesRequest(BaseModel):
    """Request for AI-generated suggested messages."""
    session_id: str
    conversation_history: Optional[List[Dict[str, str]]] = None  # List of {role: "user"|"assistant", content: "..."}


class SuggestedMessagesResponse(BaseModel):
    """Response with AI-generated suggested messages."""
    suggested_messages: List[str]
    usage: Optional[Dict[str, Any]] = None



# Pydantic AI Agent Setup
# OpenAI model reads API key from OPENAI_API_KEY environment variable automatically
openai_model = None

if OPENAI_API_KEY:
    # Just pass the model name - API key is read from environment
    try:
        openai_model = OpenAIModel(MODEL_NAME)
        logger.info("✅ OpenAI model initialized")
    except Exception as e:
        openai_model = None
        logger.error(f"❌ Failed to initialize OpenAIModel: {e}")
        logger.error("OpenAI model will be unavailable; chat endpoints may return 503 or degraded responses")
else:
    logger.warning("OpenAI model not initialized - OPENAI_API_KEY is missing")


# Tool for querying Railway PostgreSQL (file metadata, user data)
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
        db = await get_railway_db()
        if not db:
            return "Railway PostgreSQL database is not configured."
    except Exception as e:
        return f"Failed to initialize Railway PostgreSQL database: {e}"
    
    try:
        # Parse the query and construct appropriate SQL
        query_lower = query.lower()
        
        # File-related queries
        if any(word in query_lower for word in ['file', 'upload', 'document', 'document']):
            if 'count' in query_lower or 'total' in query_lower or 'number' in query_lower:
                result = await railway_db.fetchval(
                    "SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'"
                )
                return f"Total active files in the system: {result}"
            elif 'recent' in query_lower or 'latest' in query_lower:
                files = await railway_db.fetch(
                    """
                    SELECT display_name, mime_type, size_bytes, uploaded_at
                    FROM file_uploads
                    WHERE gemini_state = 'ACTIVE'
                    ORDER BY uploaded_at DESC
                    LIMIT 5
                    """
                )
                if files:
                    result = "Recent uploaded files:\n"
                    for f in files:
                        result += f"- {f['display_name']} ({f['mime_type']}, {f['size_bytes']} bytes, uploaded {f['uploaded_at']})\n"
                    return result
                return "No recent files found."
            else:
                # General file info
                files = await railway_db.fetch(
                    """
                    SELECT display_name, mime_type, size_bytes, uploaded_at
                    FROM file_uploads
                    WHERE gemini_state = 'ACTIVE'
                    ORDER BY uploaded_at DESC
                    LIMIT 10
                    """
                )
                if files:
                    result = f"Found {len(files)} active files:\n"
                    for f in files:
                        result += f"- {f['display_name']} ({f['mime_type']})\n"
                    return result
                return "No files found in the database."
        
        # Metrics queries
        elif any(word in query_lower for word in ['metric', 'statistic', 'analytics', 'usage']):
            metrics = await railway_db.fetch(
                """
                SELECT metric_name, SUM(value::numeric) as total_value, unit
                FROM metrics
                WHERE recorded_at > NOW() - INTERVAL '7 days'
                GROUP BY metric_name, unit
                ORDER BY total_value DESC
                LIMIT 10
                """
            )
            if metrics:
                result = "Recent metrics (last 7 days):\n"
                for m in metrics:
                    result += f"- {m['metric_name']}: {m['total_value']} {m['unit'] or ''}\n"
                return result
            return "No metrics found."
        
        # Default: return file count
        count = await railway_db.fetchval("SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'")
        return f"Database contains {count} active files. Please be more specific about what information you need."
        
    except Exception as e:
        logger.error(f"Error querying Railway PostgreSQL: {e}")
        return f"Error querying database: {str(e)}"


# Tool for querying Neon DB (business data)
async def query_neon_db(
    query: Annotated[str, "Natural language question about business data: products, orders, customers, sales, inventory"]
) -> str:
    """
    Query Neon DB business database for product, order, customer, sales, or inventory information.
    
    Use this for questions about:
    - Products and product catalog
    - Orders and transactions
    - Sales analytics and trends
    - Inventory levels
    - Customer segments (anonymized, no PII)
    
    IMPORTANT: Never expose PII. Only return aggregated business data, product information, and anonymized statistics.
    """
    try:
        db = await get_neon_db()
        if not db:
            return "Neon DB business database is not configured."
    except Exception as e:
        return f"Failed to initialize Neon DB business database: {e}"
    
    try:
        query_lower = query.lower()
        
        # Product queries
        if any(word in query_lower for word in ['product', 'item', 'catalog']):
            if 'available' in query_lower or 'stock' in query_lower:
                products = await neon_db.fetch(
                    """
                    SELECT product_name, category, price, stock_quantity, rating
                    FROM products
                    WHERE is_available = TRUE AND stock_quantity > 0
                    ORDER BY rating DESC NULLS LAST
                    LIMIT 10
                    """
                )
                if products:
                    result = "Available products:\n"
                    for p in products:
                        result += f"- {p['product_name']} ({p['category']}) - ${p['price']}, Stock: {p['stock_quantity']}, Rating: {p['rating'] or 'N/A'}\n"
                    return result
                return "No available products found."
            elif 'category' in query_lower:
                categories = await neon_db.fetch(
                    """
                    SELECT category, COUNT(*) as count, AVG(price) as avg_price
                    FROM products
                    WHERE is_available = TRUE
                    GROUP BY category
                    ORDER BY count DESC
                    """
                )
                if categories:
                    result = "Products by category:\n"
                    for c in categories:
                        result += f"- {c['category']}: {c['count']} products, Average price: ${float(c['avg_price']):.2f}\n"
                    return result
                return "No category data found."
            else:
                products = await neon_db.fetch(
                    "SELECT product_name, category, price FROM products WHERE is_available = TRUE LIMIT 10"
                )
                if products:
                    result = "Sample products:\n"
                    for p in products:
                        result += f"- {p['product_name']} ({p['category']}) - ${p['price']}\n"
                    return result
                return "No products found."
        
        # Order queries
        elif any(word in query_lower for word in ['order', 'transaction', 'purchase']):
            if 'recent' in query_lower or 'latest' in query_lower:
                orders = await neon_db.fetch(
                    """
                    SELECT order_id, order_status, total_amount, order_date
                    FROM orders
                    ORDER BY order_date DESC
                    LIMIT 5
                    """
                )
                if orders:
                    result = "Recent orders:\n"
                    for o in orders:
                        result += f"- Order {o['order_id']}: ${o['total_amount']} ({o['order_status']}) on {o['order_date']}\n"
                    return result
                return "No recent orders found."
            elif 'total' in query_lower or 'revenue' in query_lower:
                revenue = await neon_db.fetchval(
                    "SELECT SUM(total_amount) FROM orders WHERE order_status != 'cancelled'"
                )
                count = await neon_db.fetchval(
                    "SELECT COUNT(*) FROM orders WHERE order_status != 'cancelled'"
                )
                return f"Total revenue: ${float(revenue or 0):.2f} from {count} orders."
            else:
                orders = await neon_db.fetch(
                    """
                    SELECT order_status, COUNT(*) as count, SUM(total_amount) as total
                    FROM orders
                    GROUP BY order_status
                    """
                )
                if orders:
                    result = "Orders by status:\n"
                    for o in orders:
                        result += f"- {o['order_status']}: {o['count']} orders, Total: ${float(o['total'] or 0):.2f}\n"
                    return result
                return "No order data found."
        
        # Sales analytics
        elif any(word in query_lower for word in ['sales', 'revenue', 'analytics', 'trend']):
            analytics = await neon_db.fetch(
                """
                SELECT category, SUM(total_revenue) as revenue, SUM(total_orders) as orders
                FROM sales_analytics
                WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                GROUP BY category
                ORDER BY revenue DESC
                LIMIT 5
                """
            )
            if analytics:
                result = "Sales by category (last 30 days):\n"
                for a in analytics:
                    result += f"- {a['category']}: ${float(a['revenue'] or 0):.2f} revenue, {a['orders']} orders\n"
                return result
            return "No sales analytics data found."
        
        # Inventory queries
        elif any(word in query_lower for word in ['inventory', 'stock', 'warehouse']):
            inventory = await neon_db.fetch(
                """
                SELECT p.product_name, i.quantity_available, i.warehouse_location
                FROM inventory i
                JOIN products p ON i.product_id = p.product_id
                WHERE i.quantity_available < i.reorder_level
                ORDER BY i.quantity_available ASC
                LIMIT 10
                """
            )
            if inventory:
                result = "Low stock items:\n"
                for inv in inventory:
                    result += f"- {inv['product_name']}: {inv['quantity_available']} units at {inv['warehouse_location']}\n"
                return result
            return "All inventory levels are adequate."
        
        # Default response
        return "Please specify what business data you need: products, orders, sales, or inventory."
        
    except Exception as e:
        logger.error(f"Error querying Neon DB: {e}")
        return f"Error querying business database: {str(e)}"


# Tool for internet search
async def search_internet(
    query: Annotated[str, "Search query for current information from the internet"]
) -> str:
    """
    Search the internet for current information using Tavily API.
    
    Use this for questions about:
    - Current events and news
    - Real-time information
    - General knowledge not in the knowledge base
    - Recent developments or updates
    
    Only use when information is not available in RAG, PostgreSQL, or Neon DB AND settings.enable_internet_search is True.
    """
    if not tavily_client or not settings.enable_internet_search:
        return "Internet search is currently disabled in system configuration."
    # Check if internet search is explicitly enabled in the request deps
    # We'll need to pass 'deps' to this tool but for now we follow the logic
    # In Pydantic AI tools, 'deps' is passed if the argument is type-hinted
    pass # Modified below
    
    try:
        response = tavily_client.search(
            query=query,
            search_depth="basic",
            max_results=3
        )
        
        if response.get('results'):
            result_text = f"Internet search results for '{query}':\n\n"
            for idx, result in enumerate(response['results'][:3], 1):
                result_text += f"{idx}. {result.get('title', 'No title')}\n"
                result_text += f"   {result.get('content', 'No content')[:200]}...\n"
                if result.get('url'):
                    result_text += f"   Source: {result['url']}\n"
                result_text += "\n"
            return result_text
        return f"No internet search results found for '{query}'."
        
    except Exception as e:
        logger.error(f"Error searching internet: {e}")
        return f"Error performing internet search: {str(e)}"


# Define ChatSessionDeps before it's used in tools
@dataclass
class ChatSessionDeps:
    """Dependencies for chat session."""
    session_id: str

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
        import httpx
        import os
        
        # Get configuration service URL from environment
        config_service_url = os.getenv(
            'CONFIGURATION_SERVICE_URL',
            'https://configuration-service-production.up.railway.app'
        )
        
        # Call the request-human-agent endpoint
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{config_service_url}/api/v1/chat/{session_id}/request-human-agent",
                json={}
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


# Tool for querying Gemini FileSearch (RAG)
async def search_knowledge_base(query: Annotated[str, "The search query to find relevant information in uploaded documents"]) -> List[SearchResult]:
    """
    Search the knowledge base using Gemini FileSearch for relevant information.

    This tool searches through uploaded documents and scraped content to find
    information relevant to the user's query.
    """
    genai_client = get_genai_client()
    if not genai_client:
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
        # List all files in Gemini FileSearch
        # Convert generator to list
        all_files = list(genai_client.files.list())
        
        if not all_files:
            logger.warning("No files found in FileSearch store")
            return []
            
        # Filter for ACTIVE files only
        active_files = [f for f in all_files if f.state.name == "ACTIVE"]

        if not active_files:
            logger.warning("No ACTIVE files found in FileSearch store")
            return []

        # Filter out files with unsupported MIME types for semantic search
        # Only allow the supported formats: Documents (.pdf, .docx, .txt), Spreadsheets (.xlsx, .csv),
        # Presentations (.pptx), Code (.py, .js, .html, .json, .md)
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
            # Format: "Display Name | original_filename.ext" or just "original_filename.ext"
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
                logger.debug(f"File object attributes: {dir(f)}")

                # Try to get additional metadata from database
                db_metadata = {}
                try:
                    if db:
                        logger.debug(f"Attempting to fetch metadata for Gemini file: {f.name}, original_filename: {original_filename}")

                        # Test database connection
                        test_count = await db.fetchval("SELECT COUNT(*) FROM file_uploads")
                        logger.debug(f"Database connection test: {test_count} files in database")

                        # First try exact match with f.name
                        file_record = await db.fetchrow("""
                            SELECT id, cloudflare_r2_key, original_filename, display_name,
                                   mime_type, size_bytes, metadata, created_at, gemini_file_name
                            FROM file_uploads
                            WHERE gemini_file_name = $1
                            ORDER BY created_at DESC
                            LIMIT 1
                        """, f.name)

                        logger.debug(f"Exact match query result for '{f.name}': {file_record is not None}")

                        # If no exact match, try matching by original filename
                        if not file_record and original_filename:
                            logger.debug(f"No exact match for gemini_file_name '{f.name}', trying original_filename '{original_filename}'")
                            file_record = await db.fetchrow("""
                                SELECT id, cloudflare_r2_key, original_filename, display_name,
                                       mime_type, size_bytes, metadata, created_at, gemini_file_name
                                FROM file_uploads
                                WHERE original_filename = $1
                                ORDER BY created_at DESC
                                LIMIT 1
                            """, original_filename)
                            logger.debug(f"Original filename match result for '{original_filename}': {file_record is not None}")

                        # If still no match, try partial match on gemini_file_name
                        if not file_record:
                            # Extract just the filename part (after last slash)
                            filename_part = f.name.split('/')[-1] if '/' in f.name else f.name
                            logger.debug(f"Trying partial match with filename part: {filename_part}")
                            file_record = await db.fetchrow("""
                                SELECT id, cloudflare_r2_key, original_filename, display_name,
                                       mime_type, size_bytes, metadata, created_at, gemini_file_name
                                FROM file_uploads
                                WHERE gemini_file_name LIKE $1
                                ORDER BY created_at DESC
                                LIMIT 1
                            """, f"%{filename_part}%")
                            logger.debug(f"Partial match result for '{filename_part}': {file_record is not None}")

                        # As a last resort, try to find any file with similar name
                        if not file_record:
                            # Try to match the base filename without extension
                            base_name = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename
                            logger.debug(f"Trying base name match: {base_name}")
                            file_record = await db.fetchrow("""
                                SELECT id, cloudflare_r2_key, original_filename, display_name,
                                       mime_type, size_bytes, metadata, created_at, gemini_file_name
                                FROM file_uploads
                                WHERE original_filename LIKE $1 OR display_name LIKE $1
                                ORDER BY created_at DESC
                                LIMIT 1
                            """, f"%{base_name}%")
                            logger.debug(f"Base name match result for '{base_name}': {file_record is not None}")

                        # Debug: Show what we found in the database
                        if file_record:
                            logger.debug(f"Found database record: gemini_file_name='{file_record.get('gemini_file_name')}', original_filename='{file_record.get('original_filename')}', display_name='{file_record.get('display_name')}'")

                            db_metadata = {
                                'document_id': str(file_record['id']),
                                's3_key': file_record['cloudflare_r2_key'],
                                'original_filename': file_record['original_filename'] or original_filename,
                                'display_name': file_record['display_name'] or display_name,
                                'mime_type': file_record['mime_type'],
                                'size_bytes': file_record['size_bytes'],
                                'upload_date': file_record['created_at'].isoformat() if file_record['created_at'] else None,
                                'db_metadata': dict(file_record['metadata']) if file_record['metadata'] else {}
                            }
                            logger.info(f"Successfully retrieved database metadata for file {f.name}")
                        else:
                            logger.warning(f"No database record found for file {f.name} (original: {original_filename}). Available files in DB:")
                            # Debug: Show some available files
                            available_files = await db.fetch("""
                                SELECT gemini_file_name, original_filename, display_name
                                FROM file_uploads
                                ORDER BY created_at DESC
                                LIMIT 5
                            """)
                            for af in available_files:
                                logger.warning(f"  DB: gemini='{af['gemini_file_name']}', orig='{af['original_filename']}', display='{af['display_name']}'")
                except Exception as e:
                    logger.error(f"Could not fetch file metadata from database: {e}")
                    import traceback
                    logger.error(f"Database error traceback: {traceback.format_exc()}")

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
            
            # Construct the retrieval prompt
            retrieval_prompt = f"""
            You are a specialized retrieval system. Your task is to extract information from the provided files to answer the user's query.

            User Query: "{query}"

            Instructions:
            1. Search through the attached files for information relevant to the query.
            2. Extract direct quotes, data points, and context that answer the question.
            3. If the files contain the answer, provide ONLY the relevant text content without any line numbers, page references, or formatting.
            4. Do NOT include line numbers, page numbers, or section headers in your response.
            5. If the files do NOT contain the answer, state "No relevant information found in the knowledge base."

            Output Format:
            Source File: [Exact filename as shown in the file]
            Content: [Direct text content only - no line numbers, no page numbers, no formatting]
            """

            # Generate content using the new API with files attached
            contents = [*files_to_search, retrieval_prompt]
            response = genai_client.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=contents
            )

            # Log the full Gemini response for debugging token usage
            logger.info(f"🔍 Gemini RAG Response Details: usage_metadata={getattr(response, 'usage_metadata', 'NO_USAGE_METADATA')}")
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                logger.info(f"📊 Gemini RAG Usage Metadata: {response.usage_metadata}")

            # Track Gemini token usage from response (correlated with session)
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                await track_gemini_usage_from_response(response.usage_metadata, session_id, None, 'rag', 'gemini-2.5-flash-lite')

            # Parse the response to extract actual file names and clean content
            raw_response_text = response.text
            logger.debug(f"Raw Gemini response: {raw_response_text[:500]}...")

            # Clean the response to extract only the actual content
            def clean_gemini_response(response_text: str) -> str:
                """Clean Gemini response to extract only the relevant content without metadata."""
                lines = response_text.strip().split('\n')

                # Remove empty lines at start and end
                while lines and not lines[0].strip():
                    lines.pop(0)
                while lines and not lines[-1].strip():
                    lines.pop()

                # Look for "Content:" marker and extract everything after it
                content_lines = []
                found_content_marker = False

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue

                    # Skip metadata lines
                    if line.lower().startswith(('source file:', 'content:')):
                        if line.lower().startswith('content:'):
                            found_content_marker = True
                            # Extract content after "Content:" marker
                            content_part = line[8:].strip()  # Remove "Content:" prefix
                            if content_part:
                                content_lines.append(content_part)
                        continue
                    elif any(line.lower().startswith(prefix) for prefix in [
                        'relevant content:', 'extracted information:', 'summary:', 'answer:'
                    ]):
                        # Skip these headers
                        continue
                    elif found_content_marker or not any(line.lower().startswith(prefix) for prefix in [
                        'user query:', 'instructions:', 'output format:', '- '
                    ]):
                        # This is likely content
                        # Remove line numbers like "12", "13", etc. at the beginning
                        line = re.sub(r'^\d+\s*', '', line)
                        # Remove page references
                        line = re.sub(r'\bpage\s+\d+\b', '', line, flags=re.IGNORECASE)
                        line = line.strip()
                        if line:
                            content_lines.append(line)

                # Join content lines and clean up
                content = ' '.join(content_lines)

                # Remove multiple spaces and clean up
                content = re.sub(r'\s+', ' ', content)
                content = content.strip()

                # If content is too short or looks like a line number, it might be invalid
                if len(content) < 10 or re.match(r'^\d+$', content.strip()):
                    logger.warning(f"Extracted content appears invalid: '{content[:100]}...'")
                    return response_text.strip()  # Return original as fallback

                return content

            response_text = clean_gemini_response(raw_response_text)

            # Try to extract file name from response text
            # Look for "Source File: [filename]" pattern
            source_file_pattern = r'Source File:\s*([^\n]+)'
            matches = re.finditer(source_file_pattern, raw_response_text, re.IGNORECASE)

            found_files = []
            for match in matches:
                found_file_name = match.group(1).strip()
                found_files.append(found_file_name)
            
            # Determine the actual file name to use
            actual_file_name = None
            
            if found_files:
                # Try to match found file name with our file metadata
                found_name = found_files[0]
                for gemini_name, metadata in file_metadata_map.items():
                    display_name = metadata['display_name']
                    # Check if found name matches display name or is contained in it
                    if found_name in display_name or display_name in found_name:
                        # Extract original filename from the matched display_name
                        actual_file_name = metadata['original_filename']
                        logger.info(f"Matched found file '{found_name}' to original filename: {actual_file_name}")
                        break
                
                # If no match found, try to extract from the found name directly
                if not actual_file_name:
                    actual_file_name = extract_original_filename(found_name)
                    logger.info(f"Extracted original filename from response: {actual_file_name}")
            
            # Fallback: use the original filename of the first file searched
            if not actual_file_name:
                if len(files_to_search) == 1:
                    first_file_metadata = file_metadata_map.get(files_to_search[0].name, {})
                    actual_file_name = first_file_metadata.get('original_filename', 
                        getattr(files_to_search[0], 'display_name', 'Unknown File'))
                else:
                    # Multiple files - use first file's original filename
                    first_file_metadata = file_metadata_map.get(files_to_search[0].name, {})
                    actual_file_name = first_file_metadata.get('original_filename', 'Multiple Files')
            
            logger.info(f"Using file name: {actual_file_name} (searched {len(files_to_search)} files)")

            # Create a single consolidated result from the LLM's retrieval
            # This acts as the "context" for the downstream orchestration agent
            # Generate a chunk ID for this search result
            chunk_id = f"search_{uuid.uuid4().hex[:16]}"

            # Get additional metadata from file_metadata_map
            file_metadata = {}
            if files_to_search:
                file_metadata = file_metadata_map.get(files_to_search[0].name, {})

            # Extract page number from content if possible (basic heuristic)
            page_number = None
            page_match = re.search(r'Page\s*(\d+)', response_text[:200], re.IGNORECASE)
            if page_match:
                page_number = int(page_match.group(1))

            # Build comprehensive metadata
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
            # Fallback (return list of files if retrieval fails)
            # EXPOSE THE ERROR for debugging purposes
            return [SearchResult(
                file_name="System_Error",
                content=f"Error performing semantic search: {str(e)}. Files attempting to search: {', '.join(f.name for f in files_to_search)}",
                relevance_score=0.1,
                similarity_score=0.1,
                chunk_id=f"error_{uuid.uuid4().hex[:16]}",
                element_type="error",
                hierarchy_level=0,
                page_number=0,
                metadata={
                    "error_type": "search_failed",
                    "error_message": str(e),
                    "files_attempted": [f.name for f in files_to_search]
                }
            )]
        
    except Exception as e:
        logger.error(f"Error searching knowledge base: {e}")
        return []


# System prompt with intelligent routing instructions
def get_system_prompt(file_context: Optional[List[SearchResult]] = None, custom_prompt: Optional[str] = None, response_policy: Optional[int] = None) -> str:
    """Generate dynamic system prompt with intelligent data source routing."""
    base_prompt = """You are an intelligent knowledge assistant chatbot with access to multiple data sources.

Your role is to intelligently route user queries to the appropriate data source(s) to provide accurate answers.

AVAILABLE DATA SOURCES AND WHEN TO USE THEM:

1. **search_knowledge_base** (RAG - Gemini FileSearch):
   - Use for questions about content in uploaded documents, PDFs, text files
   - Use for questions about scraped website content
   - Use when the user asks about specific documents or file contents
   - This searches through semantically indexed documents

2. **query_railway_postgres** (Railway PostgreSQL):
   - Use for questions about file uploads, file metadata, upload history
   - Use for system metrics, analytics, and usage statistics
   - Use for questions about the knowledge base system itself
   - NEVER expose PII (personally identifiable information) - only return aggregated/anonymized data

3. **query_neon_db** (Neon DB - Business Database):
   - Use for questions about products, product catalog, pricing
   - Use for questions about orders, transactions, sales
   - Use for questions about inventory, stock levels, warehouse data
   - Use for sales analytics, revenue trends, business metrics
   - NEVER expose PII - only return business data and anonymized statistics

4. **search_internet** (Tavily - Internet Search):
   - Use ONLY when information is not available in other sources
   - Use for current events, real-time information, recent news
   - Use for general knowledge questions not in the knowledge base
   - Use as a last resort after checking other sources

5. **request_human_agent_connection** (Human Agent Support):
   - Use when the user explicitly asks to speak with a human, real person, or agent
   - Use when the user requests human support or assistance
   - Use when the user is frustrated and needs human help
   - Use when the query requires human judgment or cannot be answered by automated systems
   - This will connect the user to an available human agent and open the chat in their chat log

ROUTING STRATEGY & PRIORITY:
You MUST follow this strictly to find the best answer:
1. **Gemini RAG (search_knowledge_base)**: ALWAYS try this first for any question about documents, files, or specific content.
2. **Your Own Knowledge (GPT-4)**: If RAG doesn't have it, use your internal training data.
3. **Railway Database (query_railway_postgres)**: If the user asks about the system itself, file metadata, or metrics.
4. **Neon DB (query_neon_db)**: If the user asks about business data, sales, inventory, or customers.
5. **Internet (search_internet)**: Use ONLY if no other source has the answer AND the internet search tool is enabled.

When answering:
1. Intelligently select the appropriate tool(s) based on this priority.
2. If the user wants to connect to a human agent, use request_human_agent_connection tool.
3. Combine information from multiple sources if needed.
4. Provide accurate, helpful answers.
5. Clearly indicate when information is not available.
6. Mention which data source provided the information.
"""
    
    # Add response policy instructions
    if response_policy is not None:
        if response_policy <= 30:
            policy_instruction = "\n\nRESPONSE POLICY: FLEXIBLE - You may provide creative responses and use general knowledge when appropriate. You can expand beyond the provided sources if helpful."
        elif response_policy <= 70:
            policy_instruction = "\n\nRESPONSE POLICY: BALANCED - Balance between using provided sources and your general knowledge. Prefer sources but supplement when needed."
        else:
            policy_instruction = "\n\nRESPONSE POLICY: STRICT - Strictly adhere to information from provided sources. Only use information from the knowledge base, databases, or search results. Do not use general knowledge unless explicitly stated in sources."
        base_prompt += policy_instruction
    
    # Add file context if available
    if file_context:
        context_section = "\n\nAvailable knowledge base files (from RAG):\n"
        for idx, result in enumerate(file_context, 1):
            context_section += f"{idx}. {result.file_name}\n"
        base_prompt += context_section
    
    # Append custom system prompt if provided
    if custom_prompt:
        base_prompt += f"\n\n{custom_prompt}"
    
    return base_prompt


def create_session_dependency(session_id: str) -> ChatSessionDeps:
    """Create session dependency instance."""
    return ChatSessionDeps(session_id=session_id)

# Initialize base agent with all tools
def create_agent(file_context: Optional[List[SearchResult]] = None, custom_system_prompt: Optional[str] = None, response_policy: Optional[int] = None) -> Optional[Agent]:
    """Create a Pydantic AI agent with intelligent data source routing."""
    
    # Check if model is available
    if openai_model is None:
        logger.error("Cannot create agent - OpenAI API key not configured")
        return None

    # Build list of available tools
    tools = [search_knowledge_base]
    
    # Add human agent connection tool (requires session_id from deps)
    tools.append(request_human_agent_connection)
    
    # Add PostgreSQL tool if available
    if railway_db:
        tools.append(query_railway_postgres)
    
    # Add Neon DB tool if available
    if neon_db:
        tools.append(query_neon_db)
    
    # Add internet search tool if available
    if tavily_client:
        tools.append(search_internet)

    # Calculate temperature based on response policy (lower for strict, higher for flexible)
    temperature = 0.7  # Default
    if response_policy is not None:
        if response_policy <= 30:
            temperature = 0.9  # More creative for flexible
        elif response_policy <= 70:
            temperature = 0.7  # Balanced
        else:
            temperature = 0.3  # More deterministic for strict

    # Create agent with system prompt, tools, and dependencies
    # Note: Temperature adjustment would need to be done at model initialization
    # For now, we'll use the default model and adjust via system prompt
    agent = Agent(
        openai_model,
        system_prompt=get_system_prompt(file_context, custom_system_prompt, response_policy),
        tools=tools,
        deps_type=ChatSessionDeps,
    )
    
    return agent


@app.get("/")
async def root_diagnostic(request: Request):
    """Simple root endpoint for basic liveliness check."""
    logger.info(f"Root diagnostic check invoked: {request.url}")
    return {"status": "ok", "message": "Chatbot Orchestration Is Alive", "port_env": os.getenv("PORT")}

@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    logger.info(f"Health check invoked: {request.url}")
    log_endpoint_request("chatbot_orchestration", "health", request)
    return {"status": "healthy", "service": "chatbot_orchestration"}

@app.post("/chat", response_model=ChatSessionResponse)
async def chat(request: ChatRequest):
    """
    Handle chat request with Pydantic AI agent and RAG.
    
    Args:
        request: ChatRequest with message and optional session_id
    
    Returns:
        ChatSessionResponse with structured answer
    """
    try:
        # Get or create session
        session_id = request.session_id or str(uuid.uuid4())
        
        # Perform RAG search if enabled (pre-fetch context)
        file_context = []
        if request.use_rag:
            file_context = await search_knowledge_base(request.message)
        
        # Create or get session
        if session_id not in sessions:
            sessions[session_id] = {
                "created_at": datetime.utcnow().isoformat(),
                "messages": [],
            }
        
        session = sessions[session_id]
        
        # Create agent with context (dynamic prompt injection)
        # Pass system_prompt and response_policy if provided
        agent = create_agent(
            file_context, 
            custom_system_prompt=request.system_prompt,
            response_policy=request.response_policy
        )
        
        # Create dependency instance for this run
        session_dep = create_session_dependency(session_id)

        
        # Check if agent was created successfully
        if agent is None:
            raise HTTPException(
                status_code=503,
                detail="Chatbot service not configured - OpenAI API key required"
            )
        
        # Build chat history from session
        chat_history = session["messages"]
        
        # Convert chat history to agent messages
        history_messages = []
        for msg in chat_history[-10:]:  # Keep last 10 messages for context
            if msg["role"] == "user":
                history_messages.append(ModelRequest(parts=[UserPromptPart(content=msg["content"])]))
            elif msg["role"] == "assistant":
                # Ensure content is a string
                content_str = str(msg["content"]) if msg["content"] is not None else ""
                history_messages.append(ModelResponse(parts=[TextPart(content=content_str)]))
        
        # Run agent (with self-correction via model_retry)
        # Pass the current message as prompt and previous messages as history
        # Also pass the dependency instance for this specific run
        result = await agent.run(
            request.message, 
            message_history=history_messages,
            deps=session_dep
        )
        
        # Extract response text
        response_text = ""
        if hasattr(result, 'output'):
             # pydantic-ai v1.32.0 prefers .output (validated result)
             response_text = result.output if isinstance(result.output, str) else str(result.output)
        elif hasattr(result, 'data'):
             # fallback or older versions
             response_text = str(result.data)
        elif hasattr(result, 'response') and result.response:
             # fallback for raw response access attempt
             response_text = result.response.text if hasattr(result.response, 'text') else str(result.response)
        
        # Determine which data sources were used based on tool calls
        data_sources_used = []
        if request.use_rag and file_context:
            data_sources_used.append("rag")
        
        # Check if tools were called (this is a simplified check)
        # In a real implementation, you'd track tool calls from the agent result
        if hasattr(result, 'tool_calls') and result.tool_calls:
            for tool_call in result.tool_calls:
                tool_name = tool_call.get('name', '') if isinstance(tool_call, dict) else str(tool_call)
                if 'postgres' in tool_name.lower() or 'railway' in tool_name.lower():
                    if 'postgres' not in data_sources_used:
                        data_sources_used.append("postgres")
                elif 'neon' in tool_name.lower():
                    if 'neon_db' not in data_sources_used:
                        data_sources_used.append("neon_db")
                elif 'internet' in tool_name.lower() or 'search' in tool_name.lower():
                    if 'internet' not in data_sources_used:
                        data_sources_used.append("internet")
        
        # Build structured response
        response_data = ChatResponse(
            answer=response_text,
            sources=file_context,
            confidence=0.8,  # Default confidence
            data_sources_used=data_sources_used if data_sources_used else ["rag"] if file_context else []
        )

        # Extract usage information from agent result (ensure defined before DB persistence)
        usage_info = None
        try:
            # Try to get usage from pydantic-ai result object
            usage_obj = None
            if hasattr(result, 'usage') and result.usage:
                usage_obj = result.usage
            # Try to access underlying model response if available
            elif hasattr(result, '_model_response') and hasattr(result._model_response, 'usage'):
                usage_obj = result._model_response.usage
            elif hasattr(result, '_last_model_response') and hasattr(result._last_model_response, 'usage'):
                usage_obj = result._last_model_response.usage
            # Try to access the model's last response
            elif hasattr(result, '_last_response') and hasattr(result._last_response, 'usage'):
                usage_obj = result._last_response.usage

            if usage_obj:
                usage_info = {
                    "input_tokens": getattr(usage_obj, 'input_tokens', 0) or getattr(usage_obj, 'prompt_tokens', 0),
                    "output_tokens": getattr(usage_obj, 'output_tokens', 0) or getattr(usage_obj, 'completion_tokens', 0),
                }
                # Track token usage in database with session and message correlation
                await track_openai_usage_from_response(usage_obj, str(session_db_id), str(assistant_message_id), 'chat', MODEL_NAME)
                logger.info("✅ Usage info extracted from agent result: %s", usage_info)
            else:
                logger.warning("⚠️ No usage information found in agent result, checking available attributes...")
                # Log available attributes for debugging
                available_attrs = [attr for attr in dir(result) if not attr.startswith('_') and 'usage' in attr.lower()]
                if available_attrs:
                    logger.info("📋 Available usage-related attributes: %s", available_attrs)
                else:
                    logger.warning("📋 No usage-related attributes found. Available public attributes: %s", [attr for attr in dir(result) if not attr.startswith('_')][:10])
        except Exception as e:
            logger.error("❌ Failed to extract usage info: %s", e)

        # Detailed tracing logs for each major step — helps identify which step failed
        logger.info("Chat handling progress: building response completed")
        logger.info("Chat handling progress: response length=%s, sources=%s", len(str(response_data.answer)), len(response_data.sources))
        logger.info("Chat handling progress: data_sources_used=%s", response_data.data_sources_used)

        # Ensure Railway DB is initialized (lazy init) and save message with data source tracking
        try:
            logger.info("Attempting to initialize Railway DB (lazy)...")
            db = await get_railway_db()
            logger.info("Railway DB init returned: %s", "connected" if db else "not-configured")
        except Exception as e:
            logger.exception("Railway DB lazy init failed: %s", e)
            db = None

        if not db:
            logger.info("Skipping DB persistence because no DB connection is available")
        else:
            try:
                logger.info("DB persistence: checking for existing session row for session_id=%s", session_id)
                session_db_id = await db.fetchval(
                    "SELECT id FROM chat_sessions WHERE session_id = $1",
                    session_id
                )
                logger.info("DB persistence: fetch session_db_id result=%s", session_db_id)

                if not session_db_id:
                    logger.info("DB persistence: inserting new chat_sessions row for session_id=%s", session_id)
                    session_db_id = await db.fetchval(
                        """
                        INSERT INTO chat_sessions (session_id, is_active, message_count)
                        VALUES ($1, $2, $3)
                        RETURNING id
                        """,
                        session_id,
                        True,
                        0
                    )
                    logger.info("DB persistence: inserted chat_sessions id=%s", session_db_id)
                else:
                    logger.info("DB persistence: existing chat_sessions id=%s will be used", session_db_id)

                # Save user message
                user_message_id = None
                try:
                    logger.info("DB persistence: inserting user message for session_db_id=%s", session_db_id)
                    user_message_id = await db.fetchval(
                        """
                        INSERT INTO chat_messages (session_id, role, content, used_rag, used_postgres, used_neon_db, used_internet_search)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING id
                        """,
                        session_db_id,
                        "user",
                        request.message,
                        "rag" in response_data.data_sources_used,
                        "postgres" in response_data.data_sources_used,
                        "neon_db" in response_data.data_sources_used,
                        "internet" in response_data.data_sources_used
                    )
                    logger.info("DB persistence: user message inserted with id=%s for session_db_id=%s", user_message_id, session_db_id)
                except Exception as e:
                    logger.exception("DB persistence: failed to insert user message for session_db_id=%s: %s", session_db_id, e)

                # Save assistant message
                assistant_message_id = None
                try:
                    logger.info("DB persistence: inserting assistant message for session_db_id=%s", session_db_id)
                    assistant_message_id = await db.fetchval(
                        """
                        INSERT INTO chat_messages (session_id, role, content, used_rag, used_postgres, used_neon_db, used_internet_search, confidence_score, sources, usage_info)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        RETURNING id
                        """,
                        session_db_id,
                        "bot",
                        response_data.answer,
                        "rag" in response_data.data_sources_used,
                        "postgres" in response_data.data_sources_used,
                        "neon_db" in response_data.data_sources_used,
                        "internet" in response_data.data_sources_used,
                        response_data.confidence,
                        json.dumps([{"file_name": s.file_name, "relevance_score": s.relevance_score} for s in response_data.sources]),
                        json.dumps(usage_info) if usage_info else None
                    )
                    logger.info("DB persistence: assistant message inserted with id=%s for session_db_id=%s", assistant_message_id, session_db_id)
                except Exception as e:
                    logger.exception("DB persistence: failed to insert assistant message for session_db_id=%s: %s", session_db_id, e)

                # Update session message count
                try:
                    logger.info("DB persistence: updating chat_sessions message_count for id=%s", session_db_id)
                    await db.execute(
                        "UPDATE chat_sessions SET message_count = message_count + 2, last_activity_at = CURRENT_TIMESTAMP WHERE id = $1",
                        session_db_id
                    )
                    logger.info("DB persistence: updated message_count for session_db_id=%s", session_db_id)
                except Exception as e:
                    logger.exception("DB persistence: failed to update chat_sessions for session_db_id=%s: %s", session_db_id, e)

                # Confirm messages count in DB for this session
                try:
                    count = await db.fetchval("SELECT COUNT(*) FROM chat_messages WHERE session_id = $1", session_db_id)
                    logger.info("DB persistence: chat messages count in DB for session %s: %s", session_db_id, count)
                except Exception as e:
                    logger.debug("DB persistence: could not fetch chat message count for session %s: %s", session_db_id, e)

            except Exception as e:
                logger.exception("DB persistence: unexpected error while saving chat messages: %s", e)
        
        # Update session history
        session["messages"].append({
            "role": "user",
            "content": request.message,
            "timestamp": datetime.utcnow().isoformat()
        })
        session["messages"].append({
            "role": "assistant",
            "content": response_data.answer,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Extract usage information
        usage_info = None
        try:
            # Try to get usage from pydantic-ai result object
            usage_obj = None
            if hasattr(result, 'usage') and result.usage:
                usage_obj = result.usage
            # Try to access underlying model response if available
            elif hasattr(result, '_model_response') and hasattr(result._model_response, 'usage'):
                usage_obj = result._model_response.usage
            elif hasattr(result, '_last_model_response') and hasattr(result._last_model_response, 'usage'):
                usage_obj = result._last_model_response.usage
            # Try to access the model's last response
            elif hasattr(result, '_last_response') and hasattr(result._last_response, 'usage'):
                usage_obj = result._last_response.usage

            if usage_obj:
                usage_info = {
                    "input_tokens": getattr(usage_obj, 'input_tokens', 0) or getattr(usage_obj, 'prompt_tokens', 0),
                    "output_tokens": getattr(usage_obj, 'output_tokens', 0) or getattr(usage_obj, 'completion_tokens', 0),
                }
                # Track token usage in database with session and message correlation
                await track_openai_usage_from_response(usage_obj, str(session_db_id), str(assistant_message_id), 'chat', MODEL_NAME)
                logger.info("✅ Usage info extracted from agent result: %s", usage_info)
        except Exception as e:
            logger.error("❌ Failed to extract usage info: %s", e)
        
        return ChatSessionResponse(
            session_id=session_id,
            message=request.message,
            response=response_data,
            usage=usage_info,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Error processing chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat processing failed: {str(e)}")


@app.get("/sessions")
async def list_sessions():
    """List all active chat sessions."""
    return {
        "sessions": [
            {
                "session_id": sid,
                "created_at": session["created_at"],
                "message_count": len(session["messages"])
            }
            for sid, session in sessions.items()
        ]
    }


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    if session_id in sessions:
        del sessions[session_id]
        return {"success": True, "message": f"Session {session_id} deleted"}
    else:
        raise HTTPException(status_code=404, detail="Session not found")


@app.post("/sessions/{session_id}/review")
async def review_response(session_id: str, review: HumanReviewRequest):
    """
    Human-in-the-loop review endpoint.
    
    Args:
        session_id: Session ID
        review: Review request with approval status and feedback
    
    Returns:
        Confirmation response
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    
    # Store review in session
    if "reviews" not in session:
        session["reviews"] = []
    
    session["reviews"].append({
        "approved": review.approved,
        "feedback": review.feedback,
        "corrected_answer": review.corrected_answer,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    # If webhook is configured, send notification
    webhook_url = os.getenv("HUMAN_IN_THE_LOOP_WEBHOOK_URL")
    if webhook_url and os.getenv("HUMAN_IN_THE_LOOP_ENABLED", "false").lower() == "true":
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(
                    webhook_url,
                    json={
                        "session_id": session_id,
                        "review": review.model_dump()
                    },
                    timeout=5.0
                )
        except Exception as e:
            logger.warning(f"Failed to send webhook: {e}")
    
    return {
        "success": True,
        "message": "Review recorded",
        "session_id": session_id
    }


@app.post("/suggested-messages", response_model=SuggestedMessagesResponse)
async def generate_suggested_messages(request: SuggestedMessagesRequest):
    """
    Generate AI-suggested follow-up messages based on conversation history.
    
    Args:
        request: SuggestedMessagesRequest with session_id and optional conversation_history
    
    Returns:
        SuggestedMessagesResponse with list of suggested messages
    """
    try:
        # Get conversation history from session if not provided
        conversation_history = request.conversation_history
        if not conversation_history:
            if request.session_id in sessions:
                session = sessions[request.session_id]
                conversation_history = [
                    {"role": msg["role"], "content": msg["content"]}
                    for msg in session.get("messages", [])[-10:]  # Last 10 messages
                ]
            else:
                conversation_history = []
        
        # Build context from conversation history
        context = ""
        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    context += f"User: {content}\n"
                elif role == "assistant":
                    context += f"Assistant: {content}\n"
        
        # Create a prompt for generating suggested messages
        prompt = f"""Based on the following conversation, generate 3-5 short, relevant follow-up questions or messages that a user might want to ask next. 
Keep each suggestion concise (under 40 characters) and make them helpful and contextually relevant.

Conversation:
{context if context else "This is the start of a new conversation."}

Generate suggested messages as a JSON array of strings. Example format: ["Question 1", "Question 2", "Question 3"]

Only return the JSON array, nothing else."""

        # Use OpenAI to generate suggestions
        if not openai_model:
            raise HTTPException(
                status_code=503,
                detail="OpenAI model not available - cannot generate suggested messages"
            )
        
        # Create a simple agent for generating suggestions
        suggestion_agent = Agent(
            model=openai_model,
            system_prompt="You are a helpful assistant that generates relevant follow-up questions based on conversation context. Always return a JSON array of 3-5 short suggested messages."
        )
        
        # Run the agent to generate suggestions
        result = await suggestion_agent.run(prompt)
        
        # Extract response
        response_text = ""
        if hasattr(result, 'output'):
            response_text = result.output if isinstance(result.output, str) else str(result.output)
        elif hasattr(result, 'data'):
            response_text = str(result.data)
        
        # Parse JSON array from response
        import json
        import re
        
        # Try to extract JSON array from response
        json_match = re.search(r'\[.*?\]', response_text, re.DOTALL)
        if json_match:
            try:
                suggested_messages = json.loads(json_match.group(0))
                # Ensure it's a list of strings
                if isinstance(suggested_messages, list):
                    suggested_messages = [str(msg).strip() for msg in suggested_messages if msg]
                    # Limit to 5 messages and filter empty ones
                    suggested_messages = [msg for msg in suggested_messages if msg and len(msg) <= 40][:5]
                else:
                    suggested_messages = []
            except json.JSONDecodeError:
                # Fallback: split by lines or commas
                suggested_messages = [msg.strip().strip('"\'') for msg in response_text.split('\n') if msg.strip() and len(msg.strip()) <= 40][:5]
        else:
            # Fallback: try to extract suggestions from text
            lines = [line.strip().strip('"\'') for line in response_text.split('\n') if line.strip() and len(line.strip()) <= 40]
            suggested_messages = lines[:5]
        
        # If no suggestions generated, provide defaults
        if not suggested_messages:
            suggested_messages = [
                "Tell me more",
                "What else can you help with?",
                "I have another question"
            ]
        
        # Extract usage information
        usage_info = None
        try:
            # Try to get usage from pydantic-ai result object
            usage_obj = None
            if hasattr(result, 'usage') and result.usage:
                usage_obj = result.usage
            # Try to access underlying model response if available
            elif hasattr(result, '_model_response') and hasattr(result._model_response, 'usage'):
                usage_obj = result._model_response.usage
            elif hasattr(result, '_last_model_response') and hasattr(result._last_model_response, 'usage'):
                usage_obj = result._last_model_response.usage
            # Try to access the model's last response
            elif hasattr(result, '_last_response') and hasattr(result._last_response, 'usage'):
                usage_obj = result._last_response.usage

            if usage_obj:
                usage_info = {
                    "input_tokens": getattr(usage_obj, 'input_tokens', 0) or getattr(usage_obj, 'prompt_tokens', 0),
                    "output_tokens": getattr(usage_obj, 'output_tokens', 0) or getattr(usage_obj, 'completion_tokens', 0),
                }
                # Track token usage for suggested messages generation
                await track_openai_usage_from_response(usage_obj, request.session_id, None, 'suggested_messages', MODEL_NAME)
                logger.info("✅ Usage info extracted from agent result: %s", usage_info)
        except Exception as e:
            logger.error("❌ Failed to extract usage info: %s", e)
        
        return SuggestedMessagesResponse(
            suggested_messages=suggested_messages,
            usage=usage_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating suggested messages: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate suggested messages: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    # Port selection order: Service-specific -> Railway PORT -> Default 8003
    port = int(os.getenv("CHATBOT_ORCH_PORT", os.getenv("PORT", "8003")))
    logger.info(f"🚀 Starting chatbot_orchestration service on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
