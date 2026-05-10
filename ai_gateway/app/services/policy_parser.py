"""
Parser strukturyzowanej polityki DLP w formacie markdown.

Oczekiwany format:

    # Tematy zabronione
    - numery PESEL, NIP, dowodow
    - dane klientow (imie + nazwisko + kontakt)
    - kod oznaczony CONFIDENTIAL
    - plany strategiczne i finansowe

    # Tematy dozwolone
    - ogolne pytania techniczne
    - brainstorming

    # Opis
    Dowolny tekst kontekstowy.

Sekcja "Tematy zabronione" jest wymagana i musi zawierac
co najmniej jeden bullet. Pozostale sekcje sa opcjonalne.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


_HEADING_RE = re.compile(r"^\s*#+\s*(?P<title>.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(?P<item>.+?)\s*$")

_FORBIDDEN_KEYWORDS = ("zabronion", "zakazan", "forbidden")
_ALLOWED_KEYWORDS = ("dozwolon", "bezpieczn", "allowed")


@dataclass
class ParsedPolicy:
    forbidden_topics: List[str] = field(default_factory=list)
    allowed_topics: List[str] = field(default_factory=list)
    description: str = ""

    def is_valid(self) -> bool:
        return bool(self.forbidden_topics)


class PolicyParseError(ValueError):
    """Polityka nie zawiera wymaganych sekcji."""


def _classify_section(title: str) -> str:
    lowered = title.lower()
    if any(k in lowered for k in _FORBIDDEN_KEYWORDS):
        return "forbidden"
    if any(k in lowered for k in _ALLOWED_KEYWORDS):
        return "allowed"
    return "description"


def parse(content: str) -> ParsedPolicy:
    """Parsuje markdown polityki, zwraca strukture lub rzuca PolicyParseError."""
    policy = ParsedPolicy()
    current_section: str | None = None
    description_lines: List[str] = []

    for raw_line in content.splitlines():
        heading_match = _HEADING_RE.match(raw_line)
        if heading_match:
            current_section = _classify_section(heading_match.group("title"))
            continue

        if current_section is None:
            # Tresc przed pierwszym naglowkiem - traktujemy jako opis
            if raw_line.strip():
                description_lines.append(raw_line)
            continue

        bullet_match = _BULLET_RE.match(raw_line)
        if bullet_match and current_section in ("forbidden", "allowed"):
            item = bullet_match.group("item").strip()
            if not item:
                continue
            if current_section == "forbidden":
                policy.forbidden_topics.append(item)
            else:
                policy.allowed_topics.append(item)
        elif current_section == "description" and raw_line.strip():
            description_lines.append(raw_line)

    policy.description = "\n".join(description_lines).strip()

    if not policy.is_valid():
        raise PolicyParseError(
            "Polityka musi zawierac sekcje 'Tematy zabronione' z co najmniej jednym "
            "bullet pointem (np. '- PESEL i numery dokumentow')."
        )

    return policy
