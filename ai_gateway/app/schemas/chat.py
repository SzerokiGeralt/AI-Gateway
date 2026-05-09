"""Schematy żądań/odpowiedzi czatu."""
from typing import List, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., min_length=1)
    stream: bool = True
