"""
User model.

Part of the users vertical slice - owns its own data.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    """User entity"""
    id: Optional[int] = None
    name: str = ""
    email: str = ""
    veteran_id: Optional[str] = None
    
    def __repr__(self):
        return f"User(id={self.id}, name={self.name}, email={self.email})"
