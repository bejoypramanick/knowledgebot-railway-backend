"""
Firebase Authentication Service
Verifies Firebase Auth tokens for microservices.
"""
import os
from typing import Any, Dict, Optional

import firebase_admin
from firebase_admin import auth, credentials

from knowledgebase_ingestion.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

# Global Firebase app instance
_firebase_app = None


def init_firebase_auth():
    """Initialize Firebase Admin SDK for Authentication."""
    global _firebase_app
    
    if _firebase_app is not None:
        logger.info("Firebase Auth already initialized")
        return _firebase_app
    
    try:
        # Option 1: Service account JSON file
        credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
        if credentials_path and os.path.exists(credentials_path):
            cred = credentials.Certificate(credentials_path)
            _firebase_app = firebase_admin.initialize_app(cred)
            logger.info("Firebase Auth initialized from service account file")
            return _firebase_app
        
        # Option 2: JSON string from environment variable
        credentials_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
        if credentials_json:
            import json
            cred_dict = json.loads(credentials_json)
            cred = credentials.Certificate(cred_dict)
            _firebase_app = firebase_admin.initialize_app(cred)
            logger.info("Firebase Auth initialized from environment variable")
            return _firebase_app
        
        # Option 3: Default credentials (for Google Cloud environments)
        _firebase_app = firebase_admin.initialize_app()
        logger.info("Firebase Auth initialized with default credentials")
        return _firebase_app
        
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Auth: {e}")
        raise RuntimeError(f"Firebase initialization failed: {e}")


def verify_firebase_token(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify Firebase Auth ID token and return decoded token.
    
    Args:
        id_token: Firebase Auth ID token from client
        
    Returns:
        Decoded token with user info (uid, email, etc.) or None if invalid
    """
    try:
        # Initialize if not already done
        if _firebase_app is None:
            init_firebase_auth()
        
        # Verify and decode the token
        decoded_token = auth.verify_id_token(id_token)
        
        logger.debug(f"Token verified for user: {decoded_token.get('uid')}")
        return decoded_token
        
    except firebase_admin.exceptions.InvalidArgumentError:
        logger.warning("Invalid Firebase token format")
        return None
    except firebase_admin.exceptions.ExpiredIdTokenError:
        logger.warning("Firebase token expired")
        return None
    except Exception as e:
        logger.error(f"Error verifying Firebase token: {e}")
        return None
