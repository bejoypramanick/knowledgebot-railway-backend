import asyncio
from typing import Dict

# Store for active scraping sessions
active_scraping_sessions: Dict[str, asyncio.Queue] = {}
