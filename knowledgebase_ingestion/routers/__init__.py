from .fileupload_router import router as fileupload_router
from .webcrawl_router import router as webcrawl_router
from . import task_router

__all__ = ["fileupload_router", "webcrawl_router", "task_router"]