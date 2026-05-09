"""Streaming odpowiedzi z Anthropic Claude API w formacie SSE."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Dict, List

from anthropic import AsyncAnthropic

from app.core.config import settings

logger = logging.getLogger(__name__)

_anthropic_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client


def _to_sse(text: str) -> str:
    """
    Pakuje fragment tekstu w event SSE.
    Każda linia tekstu staje się osobną linią `data:`,
    co jest poprawnym formatem SSE dla treści wieloliniowych.
    """
    lines = text.split("\n")
    return "".join(f"data: {line}\n" for line in lines) + "\n"


async def stream_response(
    messages: List[Dict[str, str]],
) -> AsyncGenerator[str, None]:
    """
    Strumieniuje odpowiedź modelu Anthropic Claude jako SSE.

    Format eventu zgodnie ze spec:
      data: {delta}\n\n
    Zakończony:
      data: [DONE]\n\n
    """
    client = _get_client()

    try:
        async with client.messages.stream(
            model=settings.ANTHROPIC_MODEL_NAME,
            max_tokens=4096,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield _to_sse(text)
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM stream error: %s", exc)
        yield _to_sse(f"[error] Anthropic API: {exc!s}")
    finally:
        yield "data: [DONE]\n\n"
