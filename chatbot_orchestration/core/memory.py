from typing import Any, Dict

# In-memory session storage
# Note: In a production environment with multiple replicas, this should be replaced with Redis or a database
sessions: Dict[str, Dict[str, Any]] = {}
