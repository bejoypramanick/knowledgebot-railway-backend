"""
Compatibility HTTPException for services that may run without FastAPI installed.
"""

try:
    from fastapi import HTTPException as HTTPException  # type: ignore
except ModuleNotFoundError:
    class HTTPException(Exception):
        def __init__(self, status_code: int, detail=None, headers=None):
            self.status_code = status_code
            self.detail = detail
            self.headers = headers
            super().__init__(detail)
