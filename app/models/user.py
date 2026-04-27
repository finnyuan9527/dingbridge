from typing import List, Optional

from pydantic import BaseModel, Field


class User(BaseModel):
    subject: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone_number: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    raw: Optional[dict] = None
