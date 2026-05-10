"""Endpoint /chat/completions — przepływ DLP → Anthropic → SSE."""
import io
import json
import logging
from typing import List

import redis.asyncio as redis_async
from docx import Document
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services import dlp_service, llm_service

ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

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
    smtp_to_override: str | None = await r.get("config:smtp_to")
    sanitized = await dlp_service.analyze_prompt(
        prompt=original_prompt,
        user_id=current_user.id,
        username=current_user.username,
        db=db,
        bt=background_tasks,
        smtp_to_override=smtp_to_override or None,
    )

    # Jesli DLP cokolwiek zmienilo, doklejamy ostre instrukcje dla Claude.
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


def _extract_text_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _extract_text_from_docx(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


@router.post("/analyze-file")
async def analyze_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    r: redis_async.Redis = Depends(get_redis),
):
    """Analizuje plik Word (.docx) lub PDF przez filtr DLP i zwraca wynik."""
    content_type = file.content_type or ""
    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if content_type not in ALLOWED_MIME and ext not in ("pdf", "docx"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Obsługiwane formaty: PDF i DOCX.",
        )

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Plik przekracza limit 10 MB.",
        )

    try:
        if ext == "pdf" or "pdf" in content_type:
            text = _extract_text_from_pdf(raw)
        else:
            text = _extract_text_from_docx(raw)
    except Exception as exc:
        logger.warning("Nie udało się odczytać pliku %s: %s", filename, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nie udało się odczytać zawartości pliku.",
        ) from exc

    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Plik nie zawiera tekstu do analizy.",
        )

    smtp_to_override: str | None = await r.get("config:smtp_to")
    sanitized = await dlp_service.analyze_prompt(
        prompt=text,
        user_id=current_user.id,
        username=current_user.username,
        db=db,
        bt=background_tasks,
        smtp_to_override=smtp_to_override or None,
    )

    is_safe = sanitized == text
    return JSONResponse({
        "filename": filename,
        "is_safe": is_safe,
        "sanitized_text": sanitized if not is_safe else None,
        "char_count": len(text),
    })