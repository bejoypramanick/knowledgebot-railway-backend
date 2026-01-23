import os
import sys
import logging
import time
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import asyncio
import json
from datetime import datetime
from pathlib import Path
# Initialize import success flag
IMPORT_SUCCESS = False

# Try to import all required modules
try:
    # Basic imports that should always work
    load_dotenv()
    
    # Add shared directory to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    
    # Import shared modules
    from shared.config import settings
    from shared.db import init_railway_db, init_neon_db, railway_db, neon_db
    from shared.token_tracker import track_gemini_usage_from_response
    from shared.firebase_auth import verify_firebase_token
    from shared.auth_middleware import get_current_user
    
    # Mark imports as successful
    IMPORT_SUCCESS = True
    print("✅ All imports successful for chatbot_orchestration service")
    
