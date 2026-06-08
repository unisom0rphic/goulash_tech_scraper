import uuid
from typing import List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str
    region: str
    limit: int = Field(default=5, ge=1, le=20)


class SupplierCard(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    contacts: str
    website: Optional[str] = None
    source: Optional[str] = None
    price: Optional[str] = None
    min_order: Optional[str] = None
    certificates: List[str] = Field(default_factory=list)
    delivery_conditions: Optional[str] = None
    region_covered: Optional[str] = None
    comment: Optional[str] = None


class SupplierCardList(BaseModel):
    """Список карточек для structured_output"""

    suppliers: List[SupplierCard]


class SearchResponse(BaseModel):
    search_id: str
    status: str  # можно enum сделать
    results: Optional[List[SupplierCard]] = None
    scores: Optional[List[float]] = None
    error: Optional[str] = None
