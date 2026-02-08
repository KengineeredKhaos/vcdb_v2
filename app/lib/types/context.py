"""Shared type definitions"""
from typing import TypedDict


class RequestContext(TypedDict):
    """Context passed through the application"""
    request_id: str
