"""
Request ID correlation middleware.

Ensures all requests have a request_id for tracing.
request_id must be provided by the client or generated at the entry point (route layer).
"""
from typing import Callable
import uuid
import logging

logger = logging.getLogger(__name__)


def get_or_create_request_id(headers: dict) -> str:
    """
    Get request_id from headers or generate a new one.
    
    This should only be called at the route entry point, never in services.
    
    Args:
        headers: Request headers dict
        
    Returns:
        request_id string
    """
    request_id = headers.get("x-request-id") or headers.get("X-Request-ID")
    
    if not request_id:
        # Generate only at entry point (route layer)
        request_id = str(uuid.uuid4())
        logger.info(f"Generated request_id: {request_id}")
    else:
        logger.info(f"Using client-provided request_id: {request_id}")
    
    return request_id


def validate_request_id(request_id: str) -> None:
    """
    Validate that a request_id is present and valid.
    
    Args:
        request_id: The request ID to validate
        
    Raises:
        ValueError: If request_id is None or empty
    """
    if not request_id:
        raise ValueError("request_id is mandatory for all operations")
    
    if not isinstance(request_id, str):
        raise ValueError(f"request_id must be a string, got {type(request_id)}")
