"""Wysyłka asynchronicznych alertów SMTP (incydenty bezpieczeństwa)."""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_alert(incident_id: str, user_id: str, reason: str) -> None:
    """
    Wysyła krótki email-alert do zespołu bezpieczeństwa.
    NIE zawiera oryginalnego promptu — tylko ID incydentu i powód.
    """
    if not settings.SMTP_HOST or not settings.SMTP_TO:
        logger.warning("SMTP nieskonfigurowane — pomijam wysyłkę alertu %s", incident_id)
        return

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = settings.SMTP_TO
    msg["Subject"] = f"[AI Gateway] Incydent DLP {incident_id}"
    msg.set_content(
        "Wykryto naruszenie polityki DLP.\n\n"
        f"ID incydentu: {incident_id}\n"
        f"User ID:      {user_id}\n"
        f"Powód:        {reason}\n\n"
        "Szczegóły dostępne w panelu administracyjnym (/admin/incidents).\n"
        "Oryginalny prompt nie jest przesyłany mailem ze względów bezpieczeństwa.\n"
    )

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            start_tls=settings.SMTP_USE_TLS,
            timeout=15,
        )
        logger.info("Wysłano alert email dla incydentu %s", incident_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Nie udało się wysłać alertu email: %s", exc)
