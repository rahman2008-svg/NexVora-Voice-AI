"""Framework-free error type. Every API error is rendered as
{"error": {"code": "...", "message": "..."}} so the UI can localise by code."""
from typing import Dict, Optional


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str,
                 headers: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
