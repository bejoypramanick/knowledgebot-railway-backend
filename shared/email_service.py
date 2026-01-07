"""
Email Service for sending confirmation and notification emails using Gmail API.
OAuth credentials are stored in PostgreSQL database.
Uses Gmail API instead of SMTP to avoid network restrictions on Railway.
"""
import os
import logging
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
import httpx

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via Gmail API with OAuth2 authentication.
    OAuth credentials are stored in PostgreSQL database.
    Uses Gmail API (HTTP) instead of SMTP to work around Railway network restrictions.
    """
    
    def __init__(self, db_connection=None):
        self.smtp_user = os.getenv('SMTP_USER')  # Gmail address for sending
        self.email_from = os.getenv('EMAIL_FROM', self.smtp_user or 'noreply@knowledgebot.com')
        self.widget_base_url = os.getenv('WIDGET_BASE_URL', 'https://widget.example.com')
        self._access_token = None
        self.db_connection = db_connection  # PostgreSQL connection for OAuth credentials
    
    async def _get_oauth_credentials_from_db(self) -> Optional[dict]:
        """Get OAuth2 credentials from PostgreSQL database."""
        if not self.db_connection:
            logger.error("Database connection not provided to email service")
            return None
        
        try:
            # Get credentials from PostgreSQL
            row = await self.db_connection.fetchrow(
                """
                SELECT client_id, client_secret, refresh_token 
                FROM email_oauth_credentials 
                WHERE id = 1
                """
            )
            
            if not row:
                logger.error("OAuth credentials not found in database. Insert credentials into email_oauth_credentials table.")
                return None
            
            return {
                'client_id': row.get('client_id'),
                'client_secret': row.get('client_secret'),
                'refresh_token': row.get('refresh_token')
            }
        except Exception as e:
            logger.error(f"Error reading OAuth credentials from database: {e}")
            return None
        
    async def _get_access_token(self) -> Optional[str]:
        """Get OAuth2 access token using refresh token from PostgreSQL."""
        # Get credentials from PostgreSQL
        if not self.db_connection:
            logger.error("Database connection not available. Cannot get OAuth credentials.")
            return None
        
        oauth_creds = await self._get_oauth_credentials_from_db()
        if not oauth_creds:
            logger.error("OAuth credentials not found in PostgreSQL. Insert credentials into email_oauth_credentials table.")
            return None
        
        if not all([oauth_creds.get('client_id'), oauth_creds.get('client_secret'), oauth_creds.get('refresh_token')]):
            logger.error("OAuth2 credentials incomplete in database. Missing client_id, client_secret, or refresh_token.")
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
    
    def _encode_message_for_gmail(self, msg: MIMEMultipart) -> str:
        """Encode email message as base64url for Gmail API."""
        # Convert message to string
        message_string = msg.as_string()
        # Encode as base64url (Gmail API requirement)
        message_bytes = message_string.encode('utf-8')
        message_b64 = base64.urlsafe_b64encode(message_bytes).decode('utf-8')
        return message_b64
        
    async def _send_email(self, to_email: str, subject: str, body_html: str, body_text: str = None) -> bool:
        """Send an email via Gmail API with OAuth2 authentication."""
        logger.info(f"📧 _send_email called for {to_email}")
        if not self.smtp_user:
            logger.error("❌ SMTP user not configured. Email not sent. Set SMTP_USER environment variable.")
            return False
        
        # Get access token
        logger.info("🔑 Attempting to get OAuth2 access token...")
        access_token = await self._get_access_token()
        if not access_token:
            logger.error("❌ Failed to obtain OAuth2 access token. Email not sent.")
            return False
        logger.info("✅ OAuth2 access token obtained successfully")
        
        # Prepare email message
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
            
            # Encode message for Gmail API
            logger.info(f"📤 Sending email to {to_email} via Gmail API...")
            message_b64 = self._encode_message_for_gmail(msg)
            
            # Send via Gmail API
            gmail_api_url = f"https://gmail.googleapis.com/gmail/v1/users/{self.smtp_user}/messages/send"
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            }
            payload = {
                'raw': message_b64
            }
            
            logger.info(f"🔌 Sending request to Gmail API...")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(gmail_api_url, json=payload, headers=headers)
                
                if response.status_code == 200:
                    logger.info(f"✅ Email sent successfully to {to_email}")
                    return True
                else:
                    logger.error(f"❌ Gmail API error: {response.status_code} - {response.text}")
                    return False
                    
        except httpx.TimeoutException:
            logger.error(f"❌ Gmail API request timed out for {to_email}")
            return False
        except httpx.RequestError as e:
            logger.error(f"❌ Gmail API request failed for {to_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to send email to {to_email}: {e}", exc_info=True)
            return False
    
    async def send_confirmation_email(self, email: str, confirmation_link: str, password: Optional[str] = None) -> bool:
        """Send confirmation email to human agent with optional password."""
        logger.info(f"📧 Preparing to send confirmation email to {email}")
        logger.info(f"Gmail sender: {self.smtp_user}")
        logger.info(f"Confirmation link: {confirmation_link}")
        
        subject = "Confirm Your Human Agent Account"
        
        password_section = ""
        if password:
            password_section = f"""
                <div class="info-box">
                    <p><strong>Your temporary password:</strong> <span class="password">{password}</span></p>
                    <p>Please use this password to log in after confirmation. You can reset it or login with Google.</p>
                </div>
            """
        
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
                <h2>Confirm Your Human Agent Account</h2>
                <p>Hello,</p>
                <p>You have been added as a human agent for the KnowledgeBot chatbot system.</p>
                {password_section}
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
        
        password_text = f"\n\nYour temporary password: {password}\nPlease use this password to log in after confirmation. You can reset it or login with Google.\n" if password else ""
        
        body_text = f"""
        Confirm Your Human Agent Account
        
        Hello,
        
        You have been added as a human agent for the KnowledgeBot chatbot system.{password_text}
        
        Please confirm your account by clicking the link below:
        {confirmation_link}
        
        If you did not request this, please ignore this email.
        
        Best regards,
        KnowledgeBot Team
        """
        
        result = await self._send_email(email, subject, body_html, body_text)
        if result:
            logger.info(f"✅ Confirmation email successfully sent to {email}")
        else:
            logger.error(f"❌ Failed to send confirmation email to {email}")
        return result
    
    async def send_confirmation_success_email(self, email: str, widget_link: str, password: str) -> bool:
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
        
        return await self._send_email(email, subject, body_html, body_text)
    
    async def send_removal_email(self, email: str) -> bool:
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
        
        return await self._send_email(email, subject, body_html, body_text)
    
    async def send_admin_confirmation_email(self, email: str, token: str, created_by: str, password: Optional[str] = None) -> bool:
        """Send admin confirmation email with optional password."""
        import os
        frontend_url = os.getenv('FRONTEND_URL', os.getenv('WIDGET_BASE_URL', self.widget_base_url))
        confirmation_link = f"{frontend_url}/admin/confirm?token={token}"
        subject = "Confirm Your Admin Account"
        
        password_section = ""
        if password:
            password_section = f"""
                <div class="info-box">
                    <p><strong>Your temporary password:</strong> <span class="password">{password}</span></p>
                    <p>Please use this password to log in. You can reset it or login with Google after confirmation.</p>
                </div>
            """
        
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
                <h2>Confirm Your Admin Account</h2>
                <p>Hello,</p>
                <p>You have been added as an administrator for the KnowledgeBot system by {created_by}.</p>
                {password_section}
                <p>Please confirm your account by clicking the link below:</p>
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
        
        password_text = f"\n\nYour temporary password: {password}\nPlease use this password to log in. You can reset it or login with Google after confirmation.\n" if password else ""
        
        body_text = f"""
        Confirm Your Admin Account
        
        Hello,
        
        You have been added as an administrator for the KnowledgeBot system by {created_by}.{password_text}
        
        Please confirm your account by clicking the link below:
        {confirmation_link}
        
        If you did not request this, please ignore this email.
        
        Best regards,
        KnowledgeBot Team
        """
        
        return await self._send_email(email, subject, body_html, body_text)


# Factory function to create email service with database connection
def create_email_service(db_connection):
    """Create email service instance with database connection."""
    return EmailService(db_connection=db_connection)
