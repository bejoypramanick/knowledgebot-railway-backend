"""
Firebase Authentication and Firestore Service
Verifies Firebase Auth tokens and manages user data in Firestore.
"""
import os
import logging
from typing import Optional, Dict, Any
import firebase_admin
from firebase_admin import credentials, auth, firestore

logger = logging.getLogger(__name__)

# Global Firebase app instance (for Auth and Firestore)
_firebase_app = None
_firestore_db = None


def init_firebase_auth():
    """Initialize Firebase Admin SDK for Authentication and Firestore."""
    global _firebase_app, _firestore_db
    
    if _firebase_app is not None:
        logger.info("Firebase Auth and Firestore already initialized")
        return _firebase_app, _firestore_db
    
    try:
        # Option 1: Service account JSON file
        credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
        if credentials_path and os.path.exists(credentials_path):
            cred = credentials.Certificate(credentials_path)
            _firebase_app = firebase_admin.initialize_app(cred)
            _firestore_db = firestore.client()
            logger.info("Firebase Auth and Firestore initialized from service account file")
            return _firebase_app, _firestore_db
        
        # Option 2: JSON string from environment variable
        credentials_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
        if credentials_json:
            import json
            cred_dict = json.loads(credentials_json)
            cred = credentials.Certificate(cred_dict)
            _firebase_app = firebase_admin.initialize_app(cred)
            _firestore_db = firestore.client()
            logger.info("Firebase Auth and Firestore initialized from environment variable")
            return _firebase_app, _firestore_db
        
        # Option 3: Default credentials (for Google Cloud environments)
        _firebase_app = firebase_admin.initialize_app()
        _firestore_db = firestore.client()
        logger.info("Firebase Auth and Firestore initialized with default credentials")
        return _firebase_app, _firestore_db
        
    except Exception as e:
        logger.error(f"Failed to initialize Firebase Auth and Firestore: {e}")
        raise RuntimeError(f"Firebase initialization failed: {e}")


def get_firestore():
    """Get Firestore database instance."""
    global _firestore_db
    if _firestore_db is None:
        init_firebase_auth()
    return _firestore_db


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


def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from Firebase Auth by UID.
    
    Args:
        uid: Firebase user UID
        
    Returns:
        User record from Firebase Auth or None
    """
    try:
        if _firebase_app is None:
            init_firebase_auth()
        
        user = auth.get_user(uid)
        return {
            'uid': user.uid,
            'email': user.email,
            'email_verified': user.email_verified,
            'display_name': user.display_name,
            'photo_url': user.photo_url,
            'disabled': user.disabled,
            'created_at': user.user_metadata.creation_timestamp if user.user_metadata else None,
        }
    except Exception as e:
        logger.error(f"Error getting user {uid}: {e}")
        return None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from Firebase Auth by email.
    
    Args:
        email: User email address
        
    Returns:
        User record from Firebase Auth or None
    """
    try:
        if _firebase_app is None:
            init_firebase_auth()
        
        user = auth.get_user_by_email(email)
        return {
            'uid': user.uid,
            'email': user.email,
            'email_verified': user.email_verified,
            'display_name': user.display_name,
            'photo_url': user.photo_url,
            'disabled': user.disabled,
            'created_at': user.user_metadata.creation_timestamp if user.user_metadata else None,
        }
    except Exception as e:
        logger.error(f"Error getting user by email {email}: {e}")
        return None

