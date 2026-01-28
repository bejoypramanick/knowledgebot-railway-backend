import logging
import os
import httpx
from typing import Annotated
from shared.config import settings
from services.chatbot_orchestration.core.database import get_railway_db, get_neon_db
from services.chatbot_orchestration.core.dependencies import ChatSessionDeps

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
                result = await db.fetchval(
                    "SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'"
                )
                return f"Total active files in the system: {result}"
            elif 'recent' in query_lower or 'latest' in query_lower:
                files = await db.fetch(
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
                files = await db.fetch(
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
            metrics = await db.fetch(
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
        count = await db.fetchval("SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'")
        return f"Database contains {count} active files. Please be more specific about what information you need."
        
    except Exception as e:
        logger.error(f"Error querying Railway PostgreSQL: {e}")
        return f"Error querying database: {str(e)}"

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
                products = await db.fetch(
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
                categories = await db.fetch(
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
                products = await db.fetch(
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
                orders = await db.fetch(
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
                revenue = await db.fetchval(
                    "SELECT SUM(total_amount) FROM orders WHERE order_status != 'cancelled'"
                )
                count = await db.fetchval(
                    "SELECT COUNT(*) FROM orders WHERE order_status != 'cancelled'"
                )
                return f"Total revenue: ${float(revenue or 0):.2f} from {count} orders."
            else:
                orders = await db.fetch(
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
            analytics = await db.fetch(
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
            inventory = await db.fetch(
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

