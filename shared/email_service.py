"""
Email Service for sending confirmation and notification emails.
"""
import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from jinja2 import Template

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending emails via SMTP."""
    
    def __init__(self):
        self.smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_user = os.getenv('SMTP_USER')
        self.smtp_password = os.getenv('SMTP_PASSWORD')
        self.email_from = os.getenv('EMAIL_FROM', 'noreply@knowledgebot.com')
        self.widget_base_url = os.getenv('WIDGET_BASE_URL', 'https://widget.example.com')
        
    def _send_email(self, to_email: str, subject: str, body_html: str, body_text: str = None) -> bool:
        """Send an email via SMTP."""
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP credentials not configured. Email not sent.")
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
            
            # Send email
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
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

