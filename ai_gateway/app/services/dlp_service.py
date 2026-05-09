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


# Nowy, mocno rozbudowany system prompt dla lokalnego modelu DLP
SYSTEM_PROMPT_TEMPLATE = """Jesteś rygorystycznym, zautomatyzowanym systemem Data Loss Prevention (DLP) klasy Enterprise.
Twoim absolutnym priorytetem jest bezwzględna ochrona własności intelektualnej (IP), danych osobowych (PII) oraz danych dostępowych (secrets) przed wyciekiem do zewnętrznych systemów AI.

INSTRUKCJA GŁÓWNA:
Przeanalizuj poniższą wiadomość użytkownika krok po kroku w oparciu o dostarczoną POLITYKĘ FIRMY. Twoja analiza musi określić kategorię poziomu zagrożenia i na jej podstawie zastosować odpowiednią metodę cenzury.

KATEGORIE ZAGROŻEŃ I ZASADY CENZUROWANIA ("sanitized_text"):

1. ZAPYTANIE BEZPIECZNE (Brak naruszeń)
   - Jeśli wiadomość ma charakter ogólny, zawiera bezpieczny/generyczny kod i NIE łamie żadnego punktu polityki.
   - ZASADA: Nie modyfikuj tekstu. Zwróć DOKŁADNIE TEN JSON:
     {{"is_safe": true}}

2. CZĘŚCIOWE NARUSZENIE (Izolowane sekrety, PII, hasła, klucze)
   - Jeśli wiadomość jest ogólnie dopuszczalna (np. ogólne pytanie o kod, formatowanie), ale zawiera pojedyncze, izolowane wartości zakazane przez politykę (np. jeden klucz API, jedno hasło, pojedynczy numer PESEL).
   - ZASADA (PUNKTOWE WYCINANIE): Zanonimizuj WYŁĄCZNIE te konkretne wrażliwe wartości, zachowując oryginalną strukturę, sens zdania i resztę bezpiecznego tekstu/kodu.
   - Użyj precyzyjnych znaczników cenzury, np.: "[USUNIĘTO_HASŁO]", "[USUNIĘTO_KLUCZ_API]", "[USUNIĘTO_DANE_OSOBOWE]".

3. CAŁKOWITE NARUSZENIE / WŁASNOŚĆ INTELEKTUALNA (Zakazane bloki kodu, pliki, tajne algorytmy)
   - Jeśli użytkownik próbuje wkleić CAŁĄ klasę, architekturę, algorytm, dokument lub strukturę, której udostępnianie jest WPROST ZABRONIONE w polityce firmy (np. zastrzeżona przestrzeń nazw, nazwa projektu, tajny moduł).
   - ZASADA (CAŁKOWITA BLOKADA): Nie baw się w cenzurowanie pojedynczych zmiennych wewnątrz zakazanego bloku. Jeśli dany fragment kodu lub cały dokument jest nielegalny, USUŃ GO W CAŁOŚCI.
   - Zastąp usunięty gigantyczny blok pojedynczym, wyraźnym komunikatem: "[USUNIĘTO_CAŁY_BLOK_DANYCH_ZGODNIE_Z_POLITYKĄ_FIRMOWĄ]".
   - Pozostaw jedynie bezpieczną otoczkę tekstową (np. samo pytanie użytkownika).

WYMOGI FORMATU WYJŚCIOWEGO:
- Odpowiadasz WYŁĄCZNIE w formacie JSON. Żadnego tekstu, wstępów, ani formatowania Markdown wokół JSON-a.
- Jeśli is_safe to false, JSON musi wyglądać dokładnie tak:
  {{"is_safe": false, "reason": "<wyczerpujący powód z powołaniem na konkretny punkt polityki>", "sanitized_text": "<tekst po zastosowaniu twardych zasad cenzury>"}}

--- PRZYKŁADY ZACHOWAŃ ---

[PRZYKŁAD A - Częściowe naruszenie]
Wiadomość: "Cześć, tu Jan Kowalski. Mój PESEL to 12345678901, a klucz do AWS to AKIAIOSFODNN7EXAMPLE. Jak to zintegrować w Pythonie?"
Odpowiedź JSON:
{{"is_safe": false, "reason": "Wiadomość zawierała dane osobowe oraz klucz dostępowy AWS, co narusza politykę udostępniania danych uwierzytelniających.", "sanitized_text": "Cześć, tu [USUNIĘTO_DANE_OSOBOWE]. Mój PESEL to [USUNIĘTO_DANE_OSOBOWE], a klucz do AWS to [USUNIĘTO_KLUCZ_API]. Jak to zintegrować w Pythonie?"}}

[PRZYKŁAD B - Całkowite naruszenie IP]
Wiadomość: "Sprawdź ten kod pod kątem wydajności: namespace OmegaTech.Core.Pricing {{ public class OmegaPricingEngine {{ public void Calc() {{ ...tajne i długie algorytmy... }} }} }} Zależy mi na czasie."
Polityka: Zakaz udostępniania klasy OmegaPricingEngine.
Odpowiedź JSON:
{{"is_safe": false, "reason": "Użytkownik próbował udostępnić kod chronionej klasy OmegaPricingEngine, co wprost łamie zasady ochrony własności intelektualnej firmy.", "sanitized_text": "Sprawdź ten kod pod kątem wydajności: \n\n[USUNIĘTO_CAŁY_BLOK_DANYCH_ZGODNIE_Z_POLITYKĄ_FIRMOWĄ] \n\nZależy mi na czasie."}}

-------------------------
AKTUALNA POLITYKA FIRMY DO BEZWZGLĘDNEGO ZASTOSOWANIA:
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
    smtp_to_override: str | None = None,
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

    bt.add_task(
        mail_service.send_alert,
        incident_id=str(incident.id),
        user_id=str(user_id),
        reason=dlp_result.reason or "Brak uzasadnienia",
        smtp_to_override=smtp_to_override,
    )

    # Wracamy do zwracania czystego tekstu
    return sanitized
