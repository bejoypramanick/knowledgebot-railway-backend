import re
from typing import List, Optional, Union

from pydantic import BaseModel, Field, validator

try:
    from email_validator import EmailNotValidError, validate_email
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

    @validator('selected_persona')
    def validate_persona(cls, v):
        if not v or not v.strip():
            raise ValueError('Persona name cannot be empty')
        return v.strip()

class ValidatedEmail(str):
    """Custom email validator with enhanced checks"""
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            try:
                validate_email(v)
            except EmailNotValidError as e:
                raise ValueError(str(e))
        return v

class AdminAccount(BaseModel):
    email: ValidatedEmail
    password: str = Field(..., min_length=8, max_length=128)

class ChatbotConfigRequest(BaseModel):
    admin_emails: Optional[List[Union[ValidatedEmail, AdminAccount]]] = Field(None, max_items=10)
    human_agents: Optional[List[ValidatedEmail]] = Field(None, max_items=20)
    hil_enabled: Optional[bool] = None
    security: Optional[SecurityUpdate] = None
    data_management: Optional[DataManagementUpdate] = None
    persona: Optional[PersonaUpdate] = None
    notifications: Optional[NotificationsUpdate] = None

    @validator('admin_emails')
    def validate_admin_emails(cls, v):
        if v is not None and len(v) > 10:
            raise ValueError('Maximum 10 admin emails allowed')
        return v

    @validator('human_agents')
    def validate_human_agents(cls, v):
        if v is not None and len(v) > 20:
            raise ValueError('Maximum 20 human agents allowed')
        return v

class PositionData(BaseModel):
    x: int = 0
    y: int = 0

    @validator('x', 'y')
    def validate_coordinates(cls, v):
        if not isinstance(v, int):
            raise ValueError(f'{coord} must be an integer')
        if abs(v) > 10000:  # Reasonable bounds
            raise ValueError(f'{coord} value is too large')

class WidgetConfigRequest(BaseModel):
    display_name: Optional[str] = Field(None, min_length=2, max_length=50)
    initial_message: Optional[str] = Field(None, min_length=5, max_length=200)
    auto_show_duration: Optional[int] = Field(None, ge=0, le=30)

# Additional request models for router endpoints
class AdminManagementRequest(BaseModel):
    email: ValidatedEmail

class PersonaRequest(BaseModel):
    persona_name: str = Field(..., min_length=1, max_length=50)
    system_prompt: str = Field(..., min_length=10, max_length=5000)
    description: Optional[str] = Field(None, max_length=500)

class NotificationRequest(BaseModel):
    user_interactions_enabled: bool = True
    error_alerts_enabled: bool = True
    feedback_requests_enabled: bool = True

class FeedbackRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=1000)
    session_id: Optional[str] = Field(None, max_length=100)
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
    profile_zoom: Optional[float] = Field(None, ge=0.1, le=5.0)
    chat_icon_zoom: Optional[float] = Field(None, ge=0.1, le=5.0)
    profile_position: Optional[PositionData] = None
    chat_icon_position: Optional[PositionData] = None
    profile_picture_filename: Optional[str] = Field(None, max_length=255)
    chat_icon_filename: Optional[str] = Field(None, max_length=255)

    @validator('suggested_messages')
    def validate_suggested_messages(cls, v):
        if v:
            for i, message in enumerate(v):
                if message:
                    message = message.strip()
                    if len(message) > 100:
                        raise ValueError(f'Suggested message {i+1} must be less than 100 characters')
                    if not message:
                        raise ValueError(f'Suggested message {i+1} cannot be empty')
        return v
