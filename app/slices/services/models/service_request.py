"""
Service request model.

Part of the services vertical slice - owns its own data.
This represents a service request made by a veteran.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServiceRequest:
    """Service request entity"""
    id: Optional[int] = None
    user_id: int = 0
    service_type: str = ""
    description: str = ""
    status: str = "pending"
    
    def __repr__(self):
        return f"ServiceRequest(id={self.id}, user_id={self.user_id}, type={self.service_type})"
