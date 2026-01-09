"""
Widget Script Generation Endpoints
Handles generation, versioning, and analytics for widget embed scripts.
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import sys
from pathlib import Path
from datetime import datetime
import json

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db
from shared.auth_middleware import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/widget", tags=["widget-scripts"])


class WidgetScriptConfig(BaseModel):
    baseUrl: str
    theme: str
    primaryColor: str
    displayName: str
    chatBubbleColor: str
    alignBubble: str
    chatIconUrl: Optional[str] = None
    profilePictureUrl: Optional[str] = None
    initialMessage: str
    autoShowDuration: int
    embedType: str = 'bubble'  # 'bubble' or 'iframe'


class WidgetScriptRequest(BaseModel):
    config: WidgetScriptConfig
    configId: Optional[str] = None  # Reference to widget config


class WidgetScriptResponse(BaseModel):
    script: str
    scriptId: str
    version: int
    configId: Optional[str] = None


def generate_bubble_script(config: WidgetScriptConfig) -> str:
    """Generate the chat bubble embed script."""
    bubble_position = 'left: 20px;' if config.alignBubble == 'left' else 'right: 20px;'
    chat_icon_url_value = config.chatIconUrl or ''
    profile_pic_url = config.profilePictureUrl or ''
    
    script = f"""<script>
  (function() {{
    // Configuration
    var config = {{
      baseUrl: '{config.baseUrl}',
      theme: '{config.theme}',
      primaryColor: '{config.primaryColor}',
      displayName: '{config.displayName}',
      chatBubbleColor: '{config.chatBubbleColor}',
      alignBubble: '{config.alignBubble}',
      chatIconUrl: '{chat_icon_url_value}',
      profilePictureUrl: '{profile_pic_url}',
      initialMessage: {json.dumps(config.initialMessage)},
      autoShowDuration: {config.autoShowDuration}
    }};
    
    // Load saved bubble position from localStorage
    var savedPosition = null;
    try {{
      var saved = localStorage.getItem('chatBubblePosition');
      if (saved) {{
        savedPosition = JSON.parse(saved);
      }}
    }} catch (e) {{
      console.error('Error loading bubble position:', e);
    }}
    
    // Create chat bubble button
    var chatBubble = document.createElement('div');
    chatBubble.id = 'knowledgebot-chat-bubble';
    var bubbleStyle = savedPosition 
      ? 'position: fixed; left: ' + savedPosition.x + 'px; top: ' + savedPosition.y + 'px; width: 60px; height: 60px; border-radius: 50%; background-color: ' + config.chatBubbleColor + '; color: white; display: flex; align-items: center; justify-content: center; cursor: grab; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15); z-index: 9999; transition: transform 0.2s ease; user-select: none;'
      : 'position: fixed; bottom: 20px; {bubble_position} width: 60px; height: 60px; border-radius: 50%; background-color: ' + config.chatBubbleColor + '; color: white; display: flex; align-items: center; justify-content: center; cursor: grab; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15); z-index: 9999; transition: transform 0.2s ease; user-select: none;';
    chatBubble.style.cssText = bubbleStyle;
    
    // Draggable functionality
    var isDragging = false;
    var dragStartPos = null;
    
    function handleDragStart(e) {{
      if (isOpen) return;
      isDragging = false;
      var clientX = e.touches ? e.touches[0].clientX : e.clientX;
      var clientY = e.touches ? e.touches[0].clientY : e.clientY;
      var rect = chatBubble.getBoundingClientRect();
      dragStartPos = {{
        x: clientX - rect.left,
        y: clientY - rect.top
      }};
      chatBubble.style.cursor = 'grabbing';
      chatBubble.style.transition = 'none';
    }}
    
    function handleDrag(e) {{
      if (!dragStartPos) return;
      if (!isDragging && (Math.abs((e.touches ? e.touches[0].clientX : e.clientX) - (dragStartPos.x + chatBubble.getBoundingClientRect().left)) > 5 || 
          Math.abs((e.touches ? e.touches[0].clientY : e.clientY) - (dragStartPos.y + chatBubble.getBoundingClientRect().top)) > 5)) {{
        isDragging = true;
      }}
      if (!isDragging) return;
      
      var clientX = e.touches ? e.touches[0].clientX : e.clientX;
      var clientY = e.touches ? e.touches[0].clientY : e.clientY;
      
      var newX = clientX - dragStartPos.x;
      var newY = clientY - dragStartPos.y;
      
      var maxX = window.innerWidth - 60;
      var maxY = window.innerHeight - 60;
      
      var constrainedX = Math.max(0, Math.min(newX, maxX));
      var constrainedY = Math.max(0, Math.min(newY, maxY));
      
      chatBubble.style.left = constrainedX + 'px';
      chatBubble.style.top = constrainedY + 'px';
      chatBubble.style.bottom = 'auto';
      chatBubble.style.right = 'auto';
      
      try {{
        localStorage.setItem('chatBubblePosition', JSON.stringify({{ x: constrainedX, y: constrainedY }}));
      }} catch (e) {{
        console.error('Error saving bubble position:', e);
      }}
    }}
    
    function handleDragEnd() {{
      if (isDragging) {{
        isDragging = false;
      }}
      dragStartPos = null;
      chatBubble.style.cursor = 'grab';
      chatBubble.style.transition = 'transform 0.2s ease, box-shadow 0.2s ease';
    }}
    
    chatBubble.addEventListener('mousedown', handleDragStart);
    chatBubble.addEventListener('touchstart', handleDragStart);
    document.addEventListener('mousemove', handleDrag);
    document.addEventListener('touchmove', handleDrag);
    document.addEventListener('mouseup', handleDragEnd);
    document.addEventListener('touchend', handleDragEnd);
    
    // Add chat icon
    if (config.chatIconUrl) {{
      var iconImg = document.createElement('img');
      iconImg.src = config.chatIconUrl;
      iconImg.style.cssText = 'width: 54px; height: 54px; border-radius: 50%; object-fit: cover; border: none;';
      iconImg.alt = 'Chat';
      chatBubble.appendChild(iconImg);
    }} else {{
      chatBubble.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>';
    }}
    
    // Create widget window
    var widgetWindow = null;
    var isOpen = false;
    
    function createWidgetWindow() {{
      if (widgetWindow) return;
      
      widgetWindow = document.createElement('div');
      widgetWindow.id = 'knowledgebot-widget-window';
      widgetWindow.style.cssText = 'position: fixed; bottom: 90px; {bubble_position} width: 400px; height: 600px; max-width: calc(100vw - 40px); max-height: calc(100vh - 120px); background-color: ' + (config.theme === 'dark' ? '#1f2937' : '#ffffff') + '; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15); z-index: 10000; display: flex; flex-direction: column; overflow: hidden;';
      
      var iframe = document.createElement('iframe');
      iframe.src = config.baseUrl + '/widget?widgetMode=true&theme=' + encodeURIComponent(config.theme) + '&primaryColor=' + encodeURIComponent(config.primaryColor) + '&displayName=' + encodeURIComponent(config.displayName);
      iframe.style.cssText = 'width: 100%; height: 100%; border: none; border-radius: 12px;';
      iframe.setAttribute('allow', 'microphone');
      iframe.setAttribute('allowfullscreen', 'true');
      
      widgetWindow.appendChild(iframe);
      document.body.appendChild(widgetWindow);
    }}
    
    function toggleWidget() {{
      if (!isOpen) {{
        createWidgetWindow();
        isOpen = true;
        chatBubble.style.transform = 'scale(1.1)';
      }} else {{
        if (widgetWindow) {{
          widgetWindow.remove();
          widgetWindow = null;
        }}
        isOpen = false;
        chatBubble.style.transform = 'scale(1)';
      }}
    }}
    
    chatBubble.addEventListener('click', function(e) {{
      if (!isDragging) {{
        e.stopPropagation();
        toggleWidget();
      }}
    }});
    
    document.addEventListener('click', function(e) {{
      if (isOpen && widgetWindow && !widgetWindow.contains(e.target) && !chatBubble.contains(e.target)) {{
        toggleWidget();
      }}
    }});
    
    chatBubble.addEventListener('mouseenter', function() {{
      if (!isOpen) {{
        this.style.transform = 'scale(1.1)';
        this.style.boxShadow = '0 6px 25px rgba(0, 0, 0, 0.2)';
      }}
    }});
    
    chatBubble.addEventListener('mouseleave', function() {{
      if (!isOpen) {{
        this.style.transform = 'scale(1)';
        this.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.15)';
      }}
    }});
    
    document.body.appendChild(chatBubble);
    
    if (config.autoShowDuration > 0) {{
      setTimeout(function() {{
        if (!isOpen) {{
          var messagePopup = document.createElement('div');
          messagePopup.style.cssText = 'position: fixed; bottom: 90px; {bubble_position} max-width: 300px; padding: 12px 16px; background-color: ' + (config.theme === 'dark' ? '#1f2937' : '#ffffff') + '; color: ' + (config.theme === 'dark' ? '#ffffff' : '#000000') + '; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15); z-index: 9998; animation: slideUp 0.3s ease;';
          messagePopup.innerHTML = '<p style="margin: 0; font-size: 14px; line-height: 1.4;">' + config.initialMessage + '</p>';
          document.body.appendChild(messagePopup);
          
          setTimeout(function() {{
            messagePopup.remove();
          }}, 5000);
        }}
      }}, config.autoShowDuration * 1000);
    }}
  }})();
</script>
<style>
  @keyframes slideUp {{
    from {{
      opacity: 0;
      transform: translateY(10px);
    }}
    to {{
      opacity: 1;
      transform: translateY(0);
    }}
  }}
</style>"""
    return script


def generate_iframe_script(config: WidgetScriptConfig) -> str:
    """Generate the iframe embed code."""
    return f"""<iframe
  src="{config.baseUrl}/widget?widgetMode=true&theme={config.theme}&primaryColor={config.primaryColor}&displayName={config.displayName}"
  width="100%"
  height="600px"
  frameborder="0"
  allow="microphone"
  allowfullscreen
  style="border: none; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);"
></iframe>"""


@router.post("/embed-script", response_model=WidgetScriptResponse)
async def generate_embed_script(
    request: WidgetScriptRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Generate widget embed script and store it for version control and analytics.
    """
    try:
        async with railway_db.acquire() as conn:
            # Generate script based on embed type
            if request.config.embedType == 'iframe':
                script_content = generate_iframe_script(request.config)
            else:
                script_content = generate_bubble_script(request.config)
            
            # Get or create script record
            script_id = None
            version = 1
            
            if request.configId:
                # Check if script exists for this config
                existing = await conn.fetchrow(
                    """
                    SELECT id, version 
                    FROM widget_scripts 
                    WHERE config_id = $1 AND is_active = TRUE
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    request.configId
                )
                
                if existing:
                    # Create new version
                    version = existing['version'] + 1
                    script_id = str(existing['id'])
                else:
                    # First version for this config
                    script_id = str(await conn.fetchval(
                        """
                        INSERT INTO widget_scripts (config_id, script_content, version, is_active, metadata)
                        VALUES ($1, $2, $3, $4, $5)
                        RETURNING id
                        """,
                        request.configId,
                        script_content,
                        version,
                        True,
                        json.dumps({
                            'theme': request.config.theme,
                            'primaryColor': request.config.primaryColor,
                            'displayName': request.config.displayName,
                            'embedType': request.config.embedType
                        })
                    ))
            else:
                # No config ID - create standalone script
                script_id = str(await conn.fetchval(
                    """
                    INSERT INTO widget_scripts (script_content, version, is_active, metadata)
                    VALUES ($1, $2, $3, $4)
                    RETURNING id
                    """,
                    script_content,
                    version,
                    True,
                    json.dumps({
                        'theme': request.config.theme,
                        'primaryColor': request.config.primaryColor,
                        'displayName': request.config.displayName,
                        'embedType': request.config.embedType
                    })
                ))
            
            logger.info(f"Generated widget script {script_id} version {version}")
            return WidgetScriptResponse(
                script=script_content,
                scriptId=script_id,
                version=version,
                configId=request.configId
            )
            
    except Exception as e:
        logger.error(f"Error generating embed script: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/embed-script/{script_id}")
async def get_embed_script(
    script_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get widget script by ID."""
    try:
        async with railway_db.acquire() as conn:
            script = await conn.fetchrow(
                """
                SELECT script_content, version, config_id, install_count, last_used_at
                FROM widget_scripts
                WHERE id = $1 AND is_active = TRUE
                """,
                script_id
            )
            
            if not script:
                raise HTTPException(status_code=404, detail="Script not found")
            
            # Update last_used_at
            await conn.execute(
                "UPDATE widget_scripts SET last_used_at = CURRENT_TIMESTAMP WHERE id = $1",
                script_id
            )
            
            return {
                'script': script['script_content'],
                'version': script['version'],
                'configId': script['config_id'],
                'installCount': script['install_count'],
                'lastUsedAt': script['last_used_at'].isoformat() if script['last_used_at'] else None
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting embed script: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/embed-script/{script_id}/track-install")
async def track_script_install(
    script_id: str
):
    """Track widget script installation (public endpoint, no auth required)."""
    try:
        async with railway_db.acquire() as conn:
            await conn.execute(
                """
                UPDATE widget_scripts 
                SET install_count = install_count + 1, last_used_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                script_id
            )
            return {'success': True, 'message': 'Installation tracked'}
            
    except Exception as e:
        logger.error(f"Error tracking script install: {e}")
        # Don't fail the request if tracking fails
        return {'success': False, 'message': 'Tracking failed but script can still be used'}
