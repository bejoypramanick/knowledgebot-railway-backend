from .router import router
from .fileupload_router import router as fileupload_router
from .webcrawl_router import router as webcrawl_router

__all__ = ["router", "fileupload_router", "webcrawl_router"]