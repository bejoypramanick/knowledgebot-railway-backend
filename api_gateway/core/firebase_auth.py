"""
Firebase Authentication and Firestore Service
Verifies Firebase Auth tokens and manages user data in Firestore.
"""
import os
from typing import Any, Dict, Optional

import firebase_admin
from firebase_admin import auth, credentials, firestore

from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

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
        # Get project ID from environment or use default
        project_id = os.getenv('FIREBASE_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT')
        
        # Option 1: Service account JSON file
        credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
        if credentials_path and os.path.exists(credentials_path):
            cred = credentials.Certificate(credentials_path)
            if project_id:
                _firebase_app = firebase_admin.initialize_app(cred, {'projectId': project_id})
            else:
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
            if project_id:
                _firebase_app = firebase_admin.initialize_app(cred, {'projectId': project_id})
            else:
                _firebase_app = firebase_admin.initialize_app(cred)
            _firestore_db = firestore.client()
            logger.info("Firebase Auth and Firestore initialized from environment variable")
            return _firebase_app, _firestore_db
        
        # Option 3: Default credentials (for Google Cloud environments)
        if project_id:
            _firebase_app = firebase_admin.initialize_app(options={'projectId': project_id})
        else:
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


def get_user_from_firestore(uid: str) -> Optional[Dict[str, Any]]:
    """
    Get user data from Firestore by Firebase UID.
    
    Args:
        uid: Firebase user UID
        
    Returns:
        User document from Firestore or None
    """
    try:
        db = get_firestore()
        if not db:
            logger.error("Firestore not initialized")
            return None
        
        doc_ref = db.collection('users').document(uid)
        doc = doc_ref.get()
        
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        # Remove redundant fields not used by frontend
        data.pop('email_verified', None)
        data.pop('created_at', None)
        data.pop('updated_at', None)
        return data
    except Exception as e:
        logger.error(f"Error getting user from Firestore {uid}: {e}")
        return None


def save_user_to_firestore(uid: str, user_data: Dict[str, Any]) -> bool:
    """
    Save or update user data in Firestore.
    
    Args:
        uid: Firebase user UID
        user_data: User data dictionary
        
    Returns:
        True if successful, False otherwise
    """
    try:
        db = get_firestore()
        if not db:
            logger.error("Firestore not initialized")
            return False
        
        doc_ref = db.collection('users').document(uid)
        
        # Add metadata
        user_data['updated_at'] = firestore.SERVER_TIMESTAMP
        
        # If document doesn't exist, add created_at
        if not doc_ref.get().exists:
            user_data['created_at'] = firestore.SERVER_TIMESTAMP
        
        doc_ref.set(user_data, merge=True)
        logger.info(f"User {uid} saved to Firestore")
        return True
    except Exception as e:
        logger.error(f"Error saving user to Firestore {uid}: {e}")
        return False


def update_user_role_in_firestore(uid: str, role: str) -> bool:
    """
    Update user role in Firestore.
    
    Args:
        uid: Firebase user UID
        role: New role ('admin', 'human_agent', 'user')
        
    Returns:
        True if successful, False otherwise
    """
    try:
        db = get_firestore()
        if not db:
            logger.error("Firestore not initialized")
            return False
        
        doc_ref = db.collection('users').document(uid)
        doc_ref.update({
            'role': role,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"User {uid} role updated to {role}")
        return True
    except Exception as e:
        logger.error(f"Error updating user role in Firestore {uid}: {e}")
        return False

