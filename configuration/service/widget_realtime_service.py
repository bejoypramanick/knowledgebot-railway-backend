"""
Widget Real-time Service
Handles real-time synchronization of widget state across all embedded widgets
"""
import asyncio
import json
import logging
from typing import Dict, Set, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class WidgetRealtimeService:
    """Service for managing real-time widget state synchronization"""
    
    def __init__(self):
        self._connections: Dict[str, Set[asyncio.WebSocketServerConnection]] = {}
        self._widget_state: Dict[str, Any] = {}
        
    async def register_connection(self, widget_id: str, websocket: asyncio.WebSocketServerConnection):
        """Register a WebSocket connection for a widget"""
        if widget_id not in self._connections:
            self._connections[widget_id] = set()
        self._connections[widget_id].add(websocket)
        
        # Send current state to new connection
        current_state = await self.get_widget_state()
        await self.send_to_connection(websocket, {
            "type": "state_update",
            "state": current_state
        })
        
        logger.info(f"Widget {widget_id} registered. Total connections: {len(self._connections.get(widget_id, []))}")
    
    async def unregister_connection(self, widget_id: str, websocket: asyncio.WebSocketServerConnection):
        """Unregister a WebSocket connection"""
        if widget_id in self._connections:
            self._connections[widget_id].discard(websocket)
            if not self._connections[widget_id]:
                del self._connections[widget_id]
        
        logger.info(f"Widget {widget_id} unregistered")
    
    async def get_widget_state(self) -> Dict[str, Any]:
        """Get current widget state from database"""
        try:
            from ..dao.widget_config_dao import WidgetConfigDAO
            dao = WidgetConfigDAO()
            config = await dao.get_widget_config()
            
            return {
                "display_chatbot": config.get("display_chatbot", True),
                "theme": config.get("theme", "light"),
                "primary_color": config.get("primary_color", "#3b82f6"),
                "display_name": config.get("display_name", "AI Assistant"),
                "updated_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting widget state: {e}")
            return {"display_chatbot": True, "error": str(e)}
    
    async def broadcast_state_change(self, changed_field: str = None):
        """Broadcast widget state change to all connected widgets"""
        try:
            current_state = await self.get_widget_state()
            message = {
                "type": "state_update",
                "state": current_state,
                "changed_field": changed_field,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Send to all connected widgets
            total_sent = 0
            for widget_id, connections in self._connections.items():
                for websocket in list(connections):  # Copy to avoid modification during iteration
                    try:
                        await self.send_to_connection(websocket, message)
                        total_sent += 1
                    except Exception as e:
                        logger.error(f"Error sending to widget {widget_id}: {e}")
                        # Remove broken connection
                        connections.discard(websocket)
            
            logger.info(f"Broadcast state change to {total_sent} connections. Field: {changed_field}")
            
        except Exception as e:
            logger.error(f"Error broadcasting state change: {e}")
    
    async def send_to_connection(self, websocket: asyncio.WebSocketServerConnection, message: Dict[str, Any]):
        """Send message to a specific WebSocket connection"""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending WebSocket message: {e}")
            raise
    
    def get_connection_stats(self) -> Dict[str, int]:
        """Get statistics about current connections"""
        return {
            "total_widgets": len(self._connections),
            "total_connections": sum(len(connections) for connections in self._connections.values()),
            "widgets": {widget_id: len(connections) for widget_id, connections in self._connections.items()}
        }

# Global instance
widget_realtime_service = WidgetRealtimeService()
