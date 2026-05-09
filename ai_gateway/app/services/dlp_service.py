"""
Warstwa DLP — analiza promptów przez lokalny model Ollama.

Kontrakt jest sztywny: model MUSI odpowiedzieć JSON-em zgodnym z DLPResult.
Jeśli odpowie czymkolwiek innym, działamy fail-open (oryginalny prompt
+ log ostrzeżenia), żeby usterka modelu nie blokowała pracy użytkownika.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict
from uuid import UUID

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


@dataclass
class AnalysisResult:
    """Wynik analizy DLP."""
    is_blocked: bool
    prompt: str          # oryginalny prompt (gdy is_blocked=False)
    reason: str = ""     # powód blokady (gdy is_blocked=True)

# Klient Ollamy (singleton).
_ollama_client: AsyncClient | None = None


def _get_client() -> AsyncClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = AsyncClient(host=settings.OLLAMA_HOST)
    return _ollama_client


SYSTEM_PROMPT_TEMPLATE = """Jesteś systemem DLP (Data Loss Prevention). Twoim zadaniem jest ocena promptu użytkownika.

Odpowiedz WYŁĄCZNIE jednym obiektem JSON — bez markdownu, bez komentarzy, bez żadnego dodatkowego tekstu.

Format odpowiedzi (wszystkie pola są wymagane):
- "is_safe": true jeśli prompt NIE narusza polityki, false jeśli narusza
- "reason": krótkie wyjaśnienie po polsku (max 2 zdania); jeśli is_safe=true napisz "Brak naruszeń"
- "sanitized_text": jeśli is_safe=true — pusty string ""; jeśli is_safe=false — tekst promptu z zamaskowanymi danymi wrażliwymi (zastąp je [ZREDAGOWANO]), zachowując resztę treści

Przykład odpowiedzi gdy BEZPIECZNY:
{{"is_safe": true, "reason": "Brak naruszeń", "sanitized_text": ""}}

Przykład odpowiedzi gdy NIEBEZPIECZNY (prompt zawierał np. PESEL 80101012345):
{{"is_safe": false, "reason": "Prompt zawiera numer PESEL.", "sanitized_text": "Zredaguj maila. Dane klienta: Jan Nowak, PESEL [ZREDAGOWANO], konto [ZREDAGOWANO]."}}

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
    smtp_to: str | None = None,
) -> AnalysisResult:
    """
    Główna funkcja warstwy DLP.

    Zwraca AnalysisResult:
      - is_blocked=False, prompt=oryginalny — gdy prompt bezpieczny lub fail-open
      - is_blocked=True, reason=powód  — gdy polityka naruszona

    Skutki uboczne przy naruszeniu: INSERT do security_incidents + alert email w tle.
    """
    # 1. Załaduj politykę
    policy_content = await _load_latest_policy(db)
    if not policy_content:
        logger.warning("DLP: brak załadowanej polityki — przepuszczam prompt bez analizy")
        return AnalysisResult(is_blocked=False, prompt=prompt)

    # 2. Zapytaj Ollamę
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(policy_content=policy_content)
    try:
        raw = await _ask_ollama(system_prompt, prompt)
    except Exception as exc:  # noqa: BLE001
        logger.error("DLP: Ollama niedostępna — fail-open. Błąd: %s", exc)
        return AnalysisResult(is_blocked=False, prompt=prompt)

    # 3. Parsuj
    dlp_result = _parse_dlp_response(raw)
    if dlp_result is None:
        logger.warning("DLP: nieparsowalna odpowiedź — fail-open")
        return AnalysisResult(is_blocked=False, prompt=prompt)

    # 4. Decyzja
    if dlp_result.is_safe:
        return AnalysisResult(is_blocked=False, prompt=prompt)

    # 4a. Naruszenie — log + alert
    reason = dlp_result.reason or "Brak uzasadnienia"
    sanitized = dlp_result.sanitized_text or "[REDACTED]"
    incident = await _record_incident(
        db=db,
        user_id=user_id,
        original=prompt,
        sanitized=sanitized,
        reason=reason,
    )
    logger.info("DLP: zarejestrowano incydent id=%s", incident.id)

    bt.add_task(
        mail_service.send_alert,
        incident_id=str(incident.id),
        user_id=str(user_id),
        reason=reason,
        smtp_to_override=smtp_to,
    )

    return AnalysisResult(is_blocked=True, prompt=prompt, reason=reason)
