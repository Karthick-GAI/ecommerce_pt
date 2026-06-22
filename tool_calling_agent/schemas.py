from typing import Optional, List
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message:     str          = Field(..., min_length=1, max_length=2000)
    customer_id: Optional[str] = None
    session_id:  Optional[str] = None   # omit to start a new session


class ChatResponse(BaseModel):
    session_id:   str
    response:     str
    tools_used:   List[str]
    turn_count:   int


class SessionSummary(BaseModel):
    session_id:   str
    customer_id:  Optional[str]
    title:        Optional[str]
    message_count: int
    created_at:   str
    updated_at:   str


class MessageOut(BaseModel):
    role:         str
    content:      Optional[str]
    tool_name:    Optional[str]
    created_at:   str
