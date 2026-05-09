"""
Warstwa DLP — analiza promptów przez lokalny model Ollama.

Kontrakt jest sztywny: model MUSI odpowiedzieć JSON-em zgodnym z DLPResult.
Jeśli odpowie czymkolwiek innym, działamy fail-open (oryginalny prompt
+ log ostrzeżenia), żeby usterka modelu nie blokowała pracy użytkownika.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict
from uuid import UUID

import redis.asyncio as redis_async
from fastapi import BackgroundTasks
from ollama import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.incident import SecurityIncident
from app.models.policy import CompanyPolicy
from app.schemas.dlp import DLPResult
from app.services import mail_service

logger = logging.getLogger(__name__)

# Klient Ollamy (singleton).
_ollama_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = AsyncClient(host=settings.OLLAMA_HOST)
    return _ollama_client


SYSTEM_PROMPT_TEMPLATE = """Jesteś systemem DLP. Oceń prompt użytkownika zgodnie z polityką firmy.
Odpowiedz WYŁĄCZNIE poprawnym JSON (bez markdownu, bez komentarzy, bez dodatkowego tekstu):
{{"is_safe": bool, "reason": "...", "sanitized_text": ""}}

Zasady:
- is_safe=true gdy prompt zgodny z polityką — wtedy sanitized_text może być pusty.
- is_safe=false gdy prompt narusza politykę — wtedy w sanitized_text zwróć wersję
  pozbawioną elementów naruszających (np. zamaskuj dane wrażliwe, usuń poufne fragmenty),
  zachowując sens ogólny pytania.
- reason: krótkie wyjaśnienie po polsku (1-2 zdania).

POLITYKA FIRMY:
{policy_content}
"""


async def _load_latest_policy(db: AsyncSession) -> str | None:
    """Pobiera content najnowszej polityki firmowej (lub None)."""
    stmt = (
        select(CompanyPolicy)
        .order_by(CompanyPolicy.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    policy = result.scalar_one_or_none()
    return policy.content if policy else None


async def _ask_ollama(system_prompt: str, user_prompt: str) -> str:
    """Wywołanie Ollamy z wymuszeniem formatu JSON."""
    client = _get_client()
    response = await client.chat(
        model=settings.OLLAMA_MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        format="json",  # ollama wymusi prawidłowy JSON
        options={"temperature": 0.0},
    )
    return response["message"]["content"]


def _parse_dlp_response(raw: str) -> DLPResult | None:
    """Parsuje odpowiedź Ollamy do DLPResult, zwraca None przy błędzie."""
    try:
        data: Dict[str, Any] = json.loads(raw)
        return DLPResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("DLP: nie udało się sparsować odpowiedzi Ollamy: %s", exc)
        return None


async def _record_incident(
    db: AsyncSession,
    user_id: UUID,
    original: str,
    sanitized: str,
    reason: str,
) -> SecurityIncident:
    """Tworzy rekord SecurityIncident i commit."""
    incident = SecurityIncident(
        user_id=user_id,
        original_prompt=original,
        sanitized_prompt=sanitized,
        reason=reason,
    )
    db.add(incident)
    await db.commit()
    await db.refresh(incident)
    return incident


async def analyze_prompt(
    prompt: str,
    user_id: UUID,
    db: AsyncSession,
    bt: BackgroundTasks,
    r: redis_async.Redis | None = None,
) -> str:
    """
    Główna funkcja warstwy DLP.

    Zwraca:
      - oryginalny prompt, jeśli zgodny z polityką (lub gdy fail-open)
      - sanitized_text, jeśli polityka naruszona

    Skutki uboczne:
      - przy naruszeniu: INSERT do security_incidents + alert email w tle.
    """
    # 1. Załaduj politykę
    policy_content = await _load_latest_policy(db)
    if not policy_content:
        logger.warning("DLP: brak załadowanej polityki — przepuszczam prompt bez analizy")
        return prompt

    # 2. Zapytaj Ollamę
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(policy_content=policy_content)
    try:
        raw = await _ask_ollama(system_prompt, prompt)
    except Exception as exc:  # noqa: BLE001
        logger.error("DLP: Ollama niedostępna — fail-open. Błąd: %s", exc)
        return prompt

    # 3. Parsuj
    dlp_result = _parse_dlp_response(raw)
    if dlp_result is None:
        logger.warning("DLP: nieparsowalna odpowiedź — fail-open")
        return prompt

    # 4. Decyzja
    if dlp_result.is_safe:
        return prompt

    # 4a. Naruszenie — log + alert
    sanitized = dlp_result.sanitized_text or "[REDACTED]"
    incident = await _record_incident(
        db=db,
        user_id=user_id,
        original=prompt,
        sanitized=sanitized,
        reason=dlp_result.reason or "Brak uzasadnienia",
    )
    # NIE logujemy oryginalnego promptu — tylko ID
    logger.info("DLP: zarejestrowano incydent id=%s", incident.id)

    smtp_to_override: str | None = None
    if r is not None:
        smtp_to_override = await r.get("config:smtp_to")

    bt.add_task(
        mail_service.send_alert,
        incident_id=str(incident.id),
        user_id=str(user_id),
        reason=dlp_result.reason or "Brak uzasadnienia",
        smtp_to_override=smtp_to_override,
    )

    return sanitized
