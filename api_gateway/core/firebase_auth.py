"""
Firebase Authentication Module
Verifies Firebase ID tokens using Firebase Admin SDK
"""
import os
import json
from typing import Optional, Dict, Any
import firebase_admin
from firebase_admin import auth, credentials

from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

# Global Firebase app instance
_firebase_app = None


def init_firebase_auth():
    """Initialize Firebase Admin SDK for token verification"""
    global _firebase_app
    
    if _firebase_app is not None:
        logger.info("Firebase Admin SDK already initialized")
        return _firebase_app
    
    try:
        # Get Firebase credentials from environment
        credentials_json = os.getenv('FIREBASE_CREDENTIALS_JSON')
        project_id = os.getenv('FIREBASE_PROJECT_ID')
        
        if not credentials_json:
            raise RuntimeError("FIREBASE_CREDENTIALS_JSON environment variable not set")
        
        if not project_id:
            raise RuntimeError("FIREBASE_PROJECT_ID environment variable not set")
        
        # Parse JSON credentials
        try:
            cred_dict = json.loads(credentials_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in FIREBASE_CREDENTIALS_JSON: {e}")
        
        # Verify project ID matches
        if cred_dict.get('project_id') != project_id:
            logger.warning(
                f"Project ID mismatch: env={project_id}, credentials={cred_dict.get('project_id')}"
            )
        
        # Initialize Firebase Admin SDK
        cred = credentials.Certificate(cred_dict)
        _firebase_app = firebase_admin.initialize_app(cred, {
            'projectId': project_id
        })
        
        logger.info(f"✅ Firebase Admin SDK initialized successfully (Project: {project_id})")
        return _firebase_app
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Firebase Admin SDK: {e}")
        raise RuntimeError(f"Firebase Admin SDK initialization failed: {e}")


def verify_firebase_token(id_token: str) -> Optional[Dict[str, Any]]:
    """
    Verify Firebase ID token and return decoded user information.
    
    Args:
        id_token: Firebase ID token from Authorization header
        
    Returns:
        Decoded token dictionary with user info, or None if verification fails
        
    Token contains:
        - uid: Firebase user ID
        - email: User email
        - email_verified: Email verification status
        - name: User display name (if available)
        - picture: User photo URL (if available)
        - iss: Token issuer
        - aud: Token audience (project ID)
        - auth_time: Authentication time
        - iat: Token issued at time
        - exp: Token expiration time
    """
    try:
        # Initialize Firebase if not already done
        if _firebase_app is None:
            init_firebase_auth()
        
        # Verify the ID token
        decoded_token = auth.verify_id_token(id_token)
        
        logger.debug(f"✅ Token verified for user: {decoded_token.get('uid')}")
        return decoded_token
        
    except auth.InvalidIdTokenError:
        logger.warning("❌ Invalid Firebase ID token format")
        return None
    except auth.ExpiredIdTokenError:
        logger.warning("❌ Firebase ID token has expired")
        return None
    except auth.RevokedIdTokenError:
        logger.warning("❌ Firebase ID token has been revoked")
        return None
    except auth.CertificateFetchError:
        logger.error("❌ Error fetching Firebase public key certificates")
        return None
    except Exception as e:
        logger.error(f"❌ Error verifying Firebase token: {e}")
        return None


def get_user_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from Firebase Auth by UID.
    
    Args:
        uid: Firebase user UID
        
    Returns:
        User record dictionary or None if not found
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
    except auth.UserNotFoundError:
        logger.warning(f"User {uid} not found in Firebase")
        return None
    except Exception as e:
        logger.error(f"Error getting user {uid}: {e}")
        return None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Get user information from Firebase Auth by email.
    
    Args:
        email: User email address
        
    Returns:
        User record dictionary or None if not found
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
    except auth.UserNotFoundError:
        logger.warning(f"User with email {email} not found in Firebase")
        return None
    except Exception as e:
        logger.error(f"Error getting user by email {email}: {e}")
        return None
