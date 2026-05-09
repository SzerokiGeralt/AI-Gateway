"""Schemat odpowiedzi DLP (z Ollamy)."""
from pydantic import BaseModel, Field


class DLPResult(BaseModel):
    """
    Sztywny kontrakt JSON zwracany przez Ollamę.
    Jeśli model zwróci coś innego, parsowanie się nie uda
    i upstream musi zachować się fail-open (oryginalny prompt + log błędu).
    """

    is_safe: bool = Field(..., description="True jeśli prompt zgodny z polityką")
    reason: str = Field(default="", description="Krótkie uzasadnienie decyzji")
    sanitized_text: str = Field(
        default="",
        description="Zanonimizowana/oczyszczona wersja promptu (jeśli is_safe=False)",
    )
