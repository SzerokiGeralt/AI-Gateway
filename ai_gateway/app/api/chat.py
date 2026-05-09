"""Endpoint /chat/completions — przepływ DLP → Anthropic → SSE."""
import json
import logging
from typing import List

import redis.asyncio as redis_async
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services import dlp_service, llm_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

CHAT_HISTORY_LIMIT = 20  # max wiadomości na historię użytkownika


async def _load_history(r: redis_async.Redis, user_id: str) -> List[dict]:
    raw = await r.get(f"chat_history:{user_id}")
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    return []


async def _save_history(r: redis_async.Redis, user_id: str, history: List[dict]) -> None:
    trimmed = history[-CHAT_HISTORY_LIMIT:]
    await r.set(f"chat_history:{user_id}", json.dumps(trimmed))


@router.post("/completions")
@limiter.limit(settings.CHAT_RATE_LIMIT)
async def chat_completions(
    request: Request,
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    r: redis_async.Redis = Depends(get_redis),
):
    """
    Przepływ:
      1. Wyciągnij ostatnią wiadomość user.
      2. Przepuść przez DLP (sanityzacja + log incydentów).
      3. Wczytaj historię z Redis, dołącz nową wiadomość.
      4. Strumieniuj odpowiedź z Anthropic w SSE.
    """
    # 1. Ostatnia wiadomość użytkownika
    last_user_msg = next(
        (m for m in reversed(payload.messages) if m.role == "user"),
        None,
    )
    if last_user_msg is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Brak wiadomości użytkownika w żądaniu",
        )

    # Zapiszmy oryginał do porównania
    original_prompt = last_user_msg.content

    # 2. DLP — może podmienić treść
    sanitized = await dlp_service.analyze_prompt(
        prompt=original_prompt,
        user_id=current_user.id,
        db=db,
        bt=background_tasks,
    )

    # --- NOWA LOGIKA: Sprawdzamy, czy DLP coś ocenzurowało ---
    system_prompt = None
# --- NOWA LOGIKA: Ostry prompt dla modelu zewnętrznego (Claude) ---
    system_prompt = None
    if sanitized != original_prompt:
        system_prompt = (
            "SYSTEM: Działasz w środowisku Enterprise z włączonym modułem Data Loss Prevention (DLP). "
            "Zapytanie użytkownika zostało wstępnie przefiltrowane – poufne loginy, hasła, klucze API "
            "lub fragmenty kodu wewnętrznego zostały zastąpione znacznikami cenzury (np. [REDACTED], gwiazdki, "
            "lub po prostu wycięte). "
            "ZASADY BEZWZGLĘDNE (CRITICAL RULES): "
            "1. Twoim zadaniem jest wyłącznie rozwiązanie problemu technicznego / udzielenie merytorycznej odpowiedzi na podstawie tego, co zostało w tekście. "
            "2. SUROWO ZABRANIA SIĘ sugerowania audytów, rotacji kluczy czy zmiany haseł. "
            "3. Poinformuj użytkownika, że jego zapytanie zawierało poufne dane, które zostały ocenzurowane, zgodnie z polityką firmy oraz że działasz na danych ocenzurowanych."
        )

    # 3. Historia + bieżąca wiadomość
    user_id = str(current_user.id)
    history = await _load_history(r, user_id)

    incoming = [m.model_dump() for m in payload.messages]
    for msg in reversed(incoming):
        if msg["role"] == "user":
            msg["content"] = sanitized
            break

    await _save_history(r, user_id, history + incoming)

    # 4. Streaming
    anthropic_messages = [
        {"role": m["role"], "content": m["content"]}
        for m in incoming
        if m["role"] in ("user", "assistant")
    ]

    # Zwracamy z doklejonym system_promptem
    return StreamingResponse(
        llm_service.stream_response(anthropic_messages, system_prompt=system_prompt),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )