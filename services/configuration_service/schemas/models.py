from pydantic import BaseModel, validator, Field
from typing import List, Optional, Union
import re

try:
    from email_validator import validate_email, EmailNotValidError
except ImportError:
    # Fallback if email_validator is not installed
    def validate_email(email, check_deliverability=True):
        # Basic email validation fallback
        email_regex = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_regex, email):
            raise ValueError('Invalid email format')
        return {'email': email}
    EmailNotValidError = ValueError

class NotificationsUpdate(BaseModel):
    user_interactions_enabled: bool
    error_alerts_enabled: bool
    feedback_requests_enabled: bool

class SecurityUpdate(BaseModel):
    response_timeout: int = Field(..., ge=15, le=300, description="Response timeout in seconds (15-300)")
    remove_pii: bool
    restrict_config: bool

    @validator('response_timeout')
    def validate_timeout(cls, v):
        if v < 15 or v > 300:
            raise ValueError('Response timeout must be between 15 and 300 seconds')
        return v

class DataManagementUpdate(BaseModel):
    backup_logs: bool

class PersonaUpdate(BaseModel):
    system_prompt: str = Field(..., min_length=10, max_length=5000)
    selected_persona: str = Field(..., min_length=1, max_length=50)

    @validator('system_prompt')
    def validate_system_prompt(cls, v):
        if not v or not v.strip():
            raise ValueError('System prompt cannot be empty')

        v = v.strip()

        # Check for potentially harmful content
        harmful_patterns = [
            r'ignore.*previous.*instructions',
            r'bypass.*security',
            r'override.*restrictions',
            r'jailbreak',
            r'override.*safety',
            r'forget.*training',
            r'do.*not.*follow.*rules'
        ]

        for pattern in harmful_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError('System prompt contains potentially harmful content')

        # Check for excessive special characters
        special_chars = re.findall(r'[!@#$%^&*()_+=\[\]{}|;:,.<>?]', v)
        if len(special_chars) > len(v) * 0.3:  # More than 30% special chars
            raise ValueError('System prompt contains too many special characters')

        return v

    @validator('selected_persona')
    def validate_persona(cls, v):
        valid_personas = [
            'friendly-receptionist', 'knowledgeable-expert',
            'fast-paced-solver', 'upselling-assistant', 'custom'
        ]
        if v not in valid_personas:
            raise ValueError(f'Invalid persona. Must be one of: {", ".join(valid_personas)}')
        return v

class ValidatedEmail(str):
    """Custom email validator with enhanced checks"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate_email

    @classmethod
    def validate_email(cls, v):
        if not v or not isinstance(v, str):
            raise ValueError('Email is required')

        v = v.strip()

        # Use email_validator for comprehensive email validation
        try:
            # This checks format, MX records, and more
            validate_email(v, check_deliverability=True)
        except EmailNotValidError as e:
            raise ValueError(f'Invalid email: {str(e)}')

        # Additional custom checks
        domain = v.split('@')[1].lower()

        # Block disposable email domains
        disposable_domains = {
            '10minutemail.com', 'temp-mail.org', 'guerrillamail.com',
            'mailinator.com', 'throwaway.email', 'yopmail.com'
        }
        if domain in disposable_domains:
            raise ValueError('Disposable email addresses not allowed')

        # Block common typos
        suspicious_domains = ['gmial.com', 'gmai.com', 'hotmai.com']
        if domain in suspicious_domains:
            raise ValueError('Please check email domain for typos')

        # Check that domain doesn't end with a number (common pattern for temp emails)
        domain_parts = domain.split('.')
        primary_domain = domain_parts[0]
        if primary_domain and primary_domain[-1].isdigit():
            raise ValueError('Domain ending with numbers not allowed')

        # Additional domain validation - check for suspicious patterns
        suspicious_patterns = [
            r'^[a-z]+\d{2,}$',  # domain with numbers at end like gmail123
            r'^temp',  # starts with temp
            r'^test',  # starts with test
            r'^spam',  # starts with spam
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, primary_domain, re.IGNORECASE):
                raise ValueError('Invalid domain pattern detected')

        return v

class AdminAccount(BaseModel):
    email: ValidatedEmail
    password: str = Field(..., min_length=8, max_length=128)

    @validator('password')
    def validate_password(cls, v):
        if not v:
            raise ValueError('Password is required')

        # Check password strength
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')

        # Must contain at least one uppercase, lowercase, and digit
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')

        return v

class ChatbotConfigRequest(BaseModel):
    admin_emails: Optional[List[Union[ValidatedEmail, AdminAccount]]] = Field(None, max_items=10)
    human_agents: Optional[List[ValidatedEmail]] = Field(None, max_items=20)
    hil_enabled: Optional[bool] = None
    notifications: Optional[NotificationsUpdate] = None
    security: Optional[SecurityUpdate] = None
    response_policy: Optional[int] = Field(None, ge=0, le=100)
    data_management: Optional[DataManagementUpdate] = None
    persona: Optional[PersonaUpdate] = None
    llm_tokens: Optional[dict] = None

    @validator('admin_emails')
    def validate_admin_emails(cls, v):
        if v is not None:
            if len(v) > 10:
                raise ValueError('Maximum 10 admin emails allowed')

            # Check for duplicates
            emails = []
            for item in v:
                if isinstance(item, str):
                    emails.append(item)
                elif hasattr(item, 'email'):
                    emails.append(item.email)

            if len(emails) != len(set(emails)):
                raise ValueError('Duplicate admin emails are not allowed')

        return v

    @validator('human_agents')
    def validate_human_agents(cls, v):
        if v is not None:
            if len(v) > 20:
                raise ValueError('Maximum 20 human agents allowed')

            # Check for duplicates
            if len(v) != len(set(v)):
                raise ValueError('Duplicate human agent emails are not allowed')

        return v

    model_config = {
        'validate_assignment': True,
        'error_msg_templates': {
            'value_error.const': 'Invalid value for field',
            'value_error.missing': 'This field is required',
        }
    }

class PositionData(BaseModel):
    x: int = 0
    y: int = 0

    def __init__(self, **data):
        super().__init__(**data)
        # Validate coordinates are reasonable
        for coord in ['x', 'y']:
            value = getattr(self, coord)
            if not isinstance(value, int):
                raise ValueError(f'{coord} must be an integer')
            if abs(value) > 10000:  # Reasonable bounds
                raise ValueError(f'{coord} value is too large')

class WidgetConfigRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=50)
    initial_message: Optional[str] = Field(None, min_length=5, max_length=200)
    auto_show_duration: Optional[int] = Field(None, ge=0, le=30)
    suggested_messages: Optional[List[str]] = Field(None, max_items=5)
    keep_showing_suggested: Optional[bool] = None
    theme: Optional[str] = Field(None, pattern=r'^(light|dark)$')
    primary_color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    use_primary_for_header: Optional[bool] = None
    chat_bubble_color: Optional[str] = Field(None, pattern=r'^#[0-9A-Fa-f]{6}$')
    align_bubble: Optional[str] = Field(None, pattern=r'^(left|right)$')
    display_chatbot: Optional[bool] = None
    profile_picture_url: Optional[str] = None
    chat_icon_url: Optional[str] = None
    # NEW FIELDS - Add zoom and position fields with proper validation
    profile_zoom: Optional[float] = Field(None, ge=0.1, le=5.0)
    chat_icon_zoom: Optional[float] = Field(None, ge=0.1, le=5.0)
    profile_position: Optional[PositionData] = None
    chat_icon_position: Optional[PositionData] = None
    # NEW FIELDS - Add filename fields for displaying original filenames
    profile_picture_filename: Optional[str] = Field(None, max_length=255)
    chat_icon_filename: Optional[str] = Field(None, max_length=255)

    @validator('display_name')
    def validate_display_name(cls, v):
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Display name must be at least 2 characters')
            if len(v) > 50:
                raise ValueError('Display name must be less than 50 characters')

            # Check for inappropriate content
            inappropriate_words = ['spam', 'scam', 'fake', 'test', 'admin', 'root', 'system']
            lower_name = v.lower()
            for word in inappropriate_words:
                if word in lower_name:
                    raise ValueError('Display name contains inappropriate content')

            # Check for excessive special characters
            special_chars = re.findall(r'[!@#$%^&*()_+=\[\]{}|;:,.<>?]', v)
            if len(special_chars) > len(v) * 0.4:  # More than 40% special chars
                raise ValueError('Display name contains too many special characters')

        return v

    @validator('suggested_messages')
    def validate_suggested_messages(cls, v):
        if v:
            for i, message in enumerate(v):
                if message:
                    message = message.strip()
                    if len(message) > 100:
                        raise ValueError(f'Suggested message {i+1} must be less than 100 characters')
                    if len(message) < 1:
                        raise ValueError(f'Suggested message {i+1} cannot be empty')
                    v[i] = message

        return v

    @validator('profile_picture_url', 'chat_icon_url')
    def validate_image_url(cls, v):
        if v:
            # Validate URL format
            url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
            if not re.match(url_pattern, v):
                raise ValueError('Invalid image URL format')

            # Check for allowed image extensions
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            if not any(v.lower().endswith(ext) for ext in allowed_extensions):
                raise ValueError('Image URL must point to a valid image file')

            # Check URL length
            if len(v) > 2048:
                raise ValueError('Image URL is too long')

        return v

    @validator('profile_picture_filename', 'chat_icon_filename')
    def validate_filename(cls, v):
        if v:
            # Basic filename validation
            if len(v) > 255:
                raise ValueError('Filename is too long')

            # Check for dangerous characters
            dangerous_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
            if any(char in v for char in dangerous_chars):
                raise ValueError('Filename contains invalid characters')

        return v

    model_config = {
        'validate_assignment': True
    }
