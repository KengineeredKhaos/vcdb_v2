# app/slices/entity/dto.py
from datetime import datetime
from typing import Optional, TypedDict


class PersonDTO(TypedDict, total=False):
    id: str
    first_name: str
    last_name: str
    email: Optional[str]
    phone: Optional[str]
    is_customer: bool
    created_at_utc: Optional[datetime]
    updated_at_utc: Optional[datetime]
