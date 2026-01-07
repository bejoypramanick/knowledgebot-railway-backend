"""
Email Service for sending confirmation and notification emails using Firebase OAuth2.
"""
import smtplib
import os
import logging
import base64
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# Try to import Firebase Admin SDK (optional)
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("Firebase Admin SDK not installed. Using direct OAuth2. Install with: pip install firebase-admin")


class EmailService:
    """Service for sending emails via SMTP with Firebase OAuth2 authentication."""
    
    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_user = os.getenv('SMTP_USER')
        self.email_from = os.getenv('EMAIL_FROM', 'noreply@knowledgebot.com')
        self.widget_base_url = os.getenv('WIDGET_BASE_URL', 'https://widget.example.com')
        self._access_token = None
        
        # Firebase OAuth2 configuration
        self.use_firebase = os.getenv('USE_FIREBASE_OAUTH', 'false').lower() == 'true'
        self.firebase_credentials_path = os.getenv('FIREBASE_CREDENTIALS_PATH')
        self.firebase_project_id = os.getenv('FIREBASE_PROJECT_ID')
        
        # Direct OAuth2 configuration (fallback or if not using Firebase)
        self.oauth2_client_id = os.getenv('GMAIL_OAUTH2_CLIENT_ID')
        self.oauth2_client_secret = os.getenv('GMAIL_OAUTH2_CLIENT_SECRET')
        self.oauth2_refresh_token = os.getenv('GMAIL_OAUTH2_REFRESH_TOKEN')
        
        # Initialize Firebase if configured
        self.firebase_app = None
        self.firestore_db = None
        if self.use_firebase and FIREBASE_AVAILABLE:
            self._init_firebase()
    
    def _init_firebase(self):
        """Initialize Firebase Admin SDK."""
        try:
            if self.firebase_credentials_path:
                # Use service account JSON file
                cred = credentials.Certificate(self.firebase_credentials_path)
                self.firebase_app = firebase_admin.initialize_app(cred)
            elif os.getenv('FIREBASE_CREDENTIALS_JSON'):
                # Use JSON string from environment variable
                cred_json = json.loads(os.getenv('FIREBASE_CREDENTIALS_JSON'))
                cred = credentials.Certificate(cred_json)
                self.firebase_app = firebase_admin.initialize_app(cred)
            else:
                # Use default credentials (for Google Cloud environments)
                self.firebase_app = firebase_admin.initialize_app()
            
            self.firestore_db = firestore.client()
            logger.info("Firebase initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {e}")
            logger.warning("Falling back to direct OAuth2")
            self.use_firebase = False
    
    def _get_oauth_credentials_from_firebase(self) -> Optional[dict]:
        """Get OAuth2 credentials from Firebase Firestore."""
        if not self.firestore_db:
            return None
        
        try:
            # Get credentials from Firestore
            doc_ref = self.firestore_db.collection('email_config').document('gmail_oauth')
            doc = doc_ref.get()
            
            if doc.exists:
                data = doc.to_dict()
                return {
                    'client_id': data.get('client_id'),
                    'client_secret': data.get('client_secret'),
                    'refresh_token': data.get('refresh_token')
                }
            else:
                logger.warning("OAuth credentials not found in Firestore")
                return None
        except Exception as e:
            logger.error(f"Error reading OAuth credentials from Firebase: {e}")
            return None
        
    def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token using refresh token (from Firebase or direct config)."""
        # Get credentials from Firebase or use direct config
        if self.use_firebase and self.firestore_db:
            oauth_creds = self._get_oauth_credentials_from_firebase()
            if not oauth_creds:
                logger.warning("Firebase OAuth credentials not found, falling back to direct config")
                oauth_creds = {
                    'client_id': self.oauth2_client_id,
                    'client_secret': self.oauth2_client_secret,
                    'refresh_token': self.oauth2_refresh_token
                }
        else:
            oauth_creds = {
                'client_id': self.oauth2_client_id,
                'client_secret': self.oauth2_client_secret,
                'refresh_token': self.oauth2_refresh_token
            }
        
        if not all([oauth_creds.get('client_id'), oauth_creds.get('client_secret'), oauth_creds.get('refresh_token')]):
            logger.warning("OAuth2 credentials not configured. Email not sent.")
            return None
        
        try:
            # Request new access token using refresh token
            token_url = "https://oauth2.googleapis.com/token"
            data = {
                "client_id": oauth_creds['client_id'],
                "client_secret": oauth_creds['client_secret'],
                "refresh_token": oauth_creds['refresh_token'],
                "grant_type": "refresh_token"
            }
            
            response = httpx.post(token_url, data=data, timeout=10)
            response.raise_for_status()
            token_data = response.json()
            
            self._access_token = token_data.get("access_token")
            logger.debug("OAuth2 access token obtained successfully")
            return self._access_token
        except Exception as e:
            logger.error(f"Failed to obtain OAuth2 access token: {e}")
            return None
    
    def _create_oauth2_string(self, user: str, access_token: str) -> str:
        """Create OAuth2 authentication string for SMTP XOAUTH2."""
        # Format: base64("user=user@example.com\x01auth=Bearer access_token\x01\x01")
        auth_string = f"user={user}\x01auth=Bearer {access_token}\x01\x01"
        return base64.b64encode(auth_string.encode()).decode()
        
    def _send_email(self, to_email: str, subject: str, body_html: str, body_text: str = None) -> bool:
        """Send an email via SMTP with OAuth2 authentication."""
        if not self.smtp_user:
            logger.warning("SMTP user not configured. Email not sent.")
            return False
        
        # Get access token
        access_token = self._get_access_token()
        if not access_token:
            logger.error("Failed to obtain OAuth2 access token. Email not sent.")
            return False
            
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email_from
            msg['To'] = to_email
            
            # Add both plain text and HTML versions
            if body_text:
                part1 = MIMEText(body_text, 'plain')
                msg.attach(part1)
            
            part2 = MIMEText(body_html, 'html')
            msg.attach(part2)
            
            # Send email with OAuth2
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)
            try:
                server.ehlo()
                server.starttls()
                server.ehlo()
                
                # Authenticate using OAuth2
                auth_string = self._create_oauth2_string(self.smtp_user, access_token)
                server.docmd('AUTH', 'XOAUTH2 ' + auth_string)
                
                server.send_message(msg)
                logger.info(f"Email sent successfully to {to_email}")
                return True
            finally:
                server.quit()
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed for {to_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False
    
    def send_confirmation_email(self, email: str, confirmation_token: str) -> bool:
        """Send confirmation email to human agent."""
        confirmation_link = f"{self.widget_base_url}/confirm?token={confirmation_token}"
        
        subject = "Confirm Your Human Agent Account"
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{ display: inline-block; padding: 12px 24px; background-color: #4F46E5; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Confirm Your Human Agent Account</h2>
                <p>Hello,</p>
                <p>You have been added as a human agent for the KnowledgeBot chatbot system.</p>
                <p>Please confirm your account by clicking the button below:</p>
                <a href="{confirmation_link}" class="button">Confirm Account</a>
                <p>Or copy and paste this link into your browser:</p>
                <p>{confirmation_link}</p>
                <p>If you did not request this, please ignore this email.</p>
                <div class="footer">
                    <p>Best regards,<br>KnowledgeBot Team</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        body_text = f"""
        Confirm Your Human Agent Account
        
        Hello,
        
        You have been added as a human agent for the KnowledgeBot chatbot system.
        
        Please confirm your account by clicking the link below:
        {confirmation_link}
        
        If you did not request this, please ignore this email.
        
        Best regards,
        KnowledgeBot Team
        """
        
        return self._send_email(email, subject, body_html, body_text)
    
    def send_confirmation_success_email(self, email: str, widget_link: str, password: str) -> bool:
        """Send confirmation success email with widget link and password."""
        subject = "Your Human Agent Account is Ready"
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .info-box {{ background-color: #f3f4f6; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .button {{ display: inline-block; padding: 12px 24px; background-color: #4F46E5; color: white; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
                .password {{ font-family: monospace; background-color: #fff; padding: 5px 10px; border: 1px solid #ddd; border-radius: 3px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Your Human Agent Account is Ready</h2>
                <p>Hello,</p>
                <p>Your account has been confirmed. You can now access the chatbot widget.</p>
                <div class="info-box">
                    <p><strong>Widget Link:</strong> <a href="{widget_link}">{widget_link}</a></p>
                    <p><strong>Password:</strong> <span class="password">{password}</span></p>
                </div>
                <p>Please log in and change your password after first login.</p>
                <a href="{widget_link}" class="button">Access Widget</a>
                <div class="footer">
                    <p>Best regards,<br>KnowledgeBot Team</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        body_text = f"""
        Your Human Agent Account is Ready
        
        Hello,
        
        Your account has been confirmed. You can now access the chatbot widget.
        
        Widget Link: {widget_link}
        Password: {password}
        
        Please log in and change your password after first login.
        
        Best regards,
        KnowledgeBot Team
        """
        
        return self._send_email(email, subject, body_html, body_text)
    
    def send_removal_email(self, email: str) -> bool:
        """Send removal notification email to human agent."""
        subject = "Human Agent Access Removed"
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .footer {{ margin-top: 30px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>Human Agent Access Removed</h2>
                <p>Hello,</p>
                <p>Your access as a human agent has been removed from the KnowledgeBot system.</p>
                <p>If you believe this is an error, please contact the administrator.</p>
                <div class="footer">
                    <p>Best regards,<br>KnowledgeBot Team</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        body_text = f"""
        Human Agent Access Removed
        
        Hello,
        
        Your access as a human agent has been removed from the KnowledgeBot system.
        
        If you believe this is an error, please contact the administrator.
        
        Best regards,
        KnowledgeBot Team
        """
        
        return self._send_email(email, subject, body_html, body_text)


# Global email service instance
email_service = EmailService()

