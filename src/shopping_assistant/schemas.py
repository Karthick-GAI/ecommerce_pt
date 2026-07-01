from typing import Optional, List
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None   # pass logged-in user's ID for personalised replies


class SourceProduct(BaseModel):
    id: str
    name: str
    category: str
    effective_price: float
    in_stock: bool
    primary_image: Optional[str] = None
    rating_avg: Optional[float] = None
    rating_count: Optional[int] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    sources: List[SourceProduct]
    parsed_filters: Optional[dict] = None
    fallback_mode: bool = False     # True when Azure OpenAI was unavailable


class MessageItem(BaseModel):
    role: str
    content: str
    created_at: str


class HistoryResponse(BaseModel):
    session_id: str
    messages: List[MessageItem]
