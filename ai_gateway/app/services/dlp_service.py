"""
Warstwa DLP - orkiestrator.

Pipeline:
  1. Polityka markdown -> lista zakazanych tematow.
  2. Warstwa 1 (Presidio): deterministyczne wykrywanie PII i sekretow.
  3. Warstwa 2 (klasyfikator zero-shot): ocena tematyczna na podstawie polityki.
  4. Decyzja:
     - tematyczne naruszenie  -> block_all (cala tresc zastapiona),
     - tylko PII/sekrety       -> redact (podmiana znaleziska na placeholder),
     - brak naruszen           -> prompt przepuszczony bez zmian.

Polityka bledu: fail-closed. Awaria warstwy 1 lub 2 = HTTP 503.
Brak polityki nie jest awaria - wylacza tylko warstwe 2 (warstwa 1 dziala dalej).
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import SecurityIncident
from app.models.policy import CompanyPolicy
from app.services import classifier_service, mail_service, presidio_service
from app.services.policy_parser import PolicyParseError
from app.services.policy_parser import parse as parse_policy

logger = logging.getLogger(__name__)

BLOCKED_PLACEHOLDER = "[CALA_TRESC_ZABLOKOWANA_PRZEZ_DLP]"


async def _load_latest_policy_text(db: AsyncSession) -> str | None:
    stmt = select(CompanyPolicy).order_by(CompanyPolicy.updated_at.desc()).limit(1)
    res = await db.execute(stmt)
    p = res.scalar_one_or_none()
    return p.content if p else None


async def _record_incident(
    db: AsyncSession,
    user_id: UUID,
    original: str,
    sanitized: str,
    reason: str,
) -> SecurityIncident:
    inc = SecurityIncident(
        user_id=user_id,
        original_prompt=original,
        sanitized_prompt=sanitized,
        reason=reason,
    )
    db.add(inc)
    await db.commit()
    await db.refresh(inc)
    return inc


def _fail_closed(detail: str = "Bledna warstwa DLP - prompt nie zostal zweryfikowany.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    )


async def analyze_prompt(
    prompt: str,
    user_id: UUID,
    username: str | None,
    db: AsyncSession,
    bt: BackgroundTasks,
    smtp_to_override: str | None = None,
) -> str:
    """
    Glowna funkcja warstwy DLP. Zwraca prompt (lub jego zsanityzowana wersje).
    Rzuca HTTPException 503 przy awarii warstwy detekcji (fail-closed).
    """
    # 1. Polityka -> etykiety zakazanych tematow
    forbidden_topics: list[str] = []
    raw_policy = await _load_latest_policy_text(db)
    if raw_policy:
        try:
            forbidden_topics = parse_policy(raw_policy).forbidden_topics
        except PolicyParseError as exc:
            logger.warning("DLP: polityka nieparsowalna - warstwa 2 wylaczona: %s", exc)
    else:
        logger.warning("DLP: brak zaladowanej polityki - warstwa 2 wylaczona")

    # 2. Warstwa 1 - Presidio (PII + sekrety)
    try:
        findings = await asyncio.to_thread(presidio_service.analyze, prompt)
    except Exception as exc:
        logger.exception("DLP: warstwa 1 (Presidio) padla")
        raise _fail_closed() from exc

    pii_types = sorted({f.entity_type for f in findings})
    sanitized = presidio_service.redact(prompt, findings) if findings else prompt
    # Osobna wersja dla klasyfikatora - bez tagow [REDACTED:TYP], ktore zaburzaly NLI
    # (model laczyl wielkie litery + dwukropek z etykietami typu 'kod oznaczony CONFIDENTIAL').
    text_for_classifier = (
        presidio_service.redact_neutral(prompt, findings) if findings else prompt
    )

    # 3. Warstwa 2 - klasyfikator pracuje na tekscie z USUNIETYMI PII (bez tagow).
    # Dzieki temu nie blokujemy block_all-em za to, co warstwa 1 juz zredagowala.
    # Naruszenie tematyczne wykryte tutaj oznacza realny problem kontekstowy,
    # niezalezny od konkretnych PII (np. "klient prosi o nasza polityke cenowa").
    topic_violation: str | None = None
    topic_score = 0.0
    if forbidden_topics:
        try:
            cls = await asyncio.to_thread(
                classifier_service.classify, text_for_classifier, forbidden_topics,
            )
        except Exception as exc:
            logger.exception("DLP: warstwa 2 (klasyfikator) padla")
            raise _fail_closed() from exc
        if cls.is_violation:
            topic_violation = cls.matched_label
            topic_score = cls.score

    # 4. Decyzja
    if topic_violation:
        sanitized = BLOCKED_PLACEHOLDER
        reason = f"Naruszenie tematyczne: '{topic_violation}' (score={topic_score:.2f})"
        if pii_types:
            reason += f"; PII: {', '.join(pii_types)}"
    elif pii_types:
        reason = f"Wykryte PII/sekrety: {', '.join(pii_types)}"
    else:
        return prompt

    # 5. Incydent + alert (mail w tle)
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
        username=username,
        reason=reason,
        smtp_to_override=smtp_to_override,
    )

    return sanitized
