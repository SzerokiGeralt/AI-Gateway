"""Wysyłka asynchronicznych alertów SMTP (incydenty bezpieczeństwa)."""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_alert(
    incident_id: str,
    user_id: str,
    username: str | None,
    reason: str,
    smtp_to_override: str | None = None,
) -> None:
    """
    Wysyła krótki email-alert do zespołu bezpieczeństwa.
    NIE zawiera oryginalnego promptu — tylko ID incydentu, login i powód.
    smtp_to_override — adres ustawiony przez admina w UI (z Redis); fallback na settings.SMTP_TO.
    """
    smtp_to = smtp_to_override or settings.SMTP_TO
    if not settings.SMTP_HOST or not smtp_to:
        logger.warning("SMTP nieskonfigurowane — pomijam wysyłkę alertu %s", incident_id)
        return

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = smtp_to
    msg["Subject"] = f"[Big Brother Proxy] Incydent DLP {incident_id}"
    msg.set_content(
        "Wykryto naruszenie polityki DLP.\n\n"
        f"ID incydentu: {incident_id}\n"
        f"User ID:      {user_id}\n"
        f"Login:        {username or '—'}\n"
        f"Powód:        {reason}\n\n"
        "Szczegóły dostępne w panelu administracyjnym (/admin/incidents).\n"
        "Oryginalny prompt nie jest przesyłany mailem ze względów bezpieczeństwa.\n"
    )

    send_kwargs: dict = {
        "hostname": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "username": settings.SMTP_USER or None,
        "password": settings.SMTP_PASSWORD or None,
        "timeout": 15,
    }
    if settings.SMTP_USE_SSL:
        send_kwargs["use_tls"] = True
    elif settings.SMTP_USE_TLS:
        send_kwargs["start_tls"] = True

    try:
        await aiosmtplib.send(msg, **send_kwargs)
        logger.info("Wysłano alert email dla incydentu %s", incident_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Nie udało się wysłać alertu email dla incydentu %s: %s: %s",
            incident_id, type(exc).__name__, exc,
        )
