"""
DLP - warstwa 1: deterministyczne wykrywanie PII i sekretow.

Presidio + custom rozpoznawacze polskie z walidacja sum kontrolnych
(PESEL, NIP, REGON, IBAN PL, dowod osobisty) oraz pakiet wzorcow
sekretow (klucze API, tokeny, klucze prywatne).

Komponent jest synchroniczny - wywolania z asyncio uruchamiaj przez
asyncio.to_thread, zeby nie blokowac event loopa.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer, RecognizerRegistry
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer,
    EmailRecognizer,
    IpRecognizer,
    PhoneRecognizer,
    UrlRecognizer,
)

logger = logging.getLogger(__name__)


# ============================================================
#  Custom rozpoznawacze polskie z walidacja checksumy
# ============================================================
class PESELRecognizer(PatternRecognizer):
    """PESEL - 11 cyfr z suma kontrolna."""

    PATTERNS = [Pattern(name="PESEL (11 digits)", regex=r"\b\d{11}\b", score=0.4)]
    CONTEXT = ["pesel", "PESEL"]

    def __init__(self):
        super().__init__(
            supported_entity="PL_PESEL",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="pl",
        )

    def validate_result(self, pattern_text: str) -> bool:
        if len(pattern_text) != 11 or not pattern_text.isdigit():
            return False
        weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
        s = sum(int(d) * w for d, w in zip(pattern_text[:10], weights))
        check = (10 - s % 10) % 10
        return check == int(pattern_text[10])


class NIPRecognizer(PatternRecognizer):
    """NIP - 10 cyfr (z opcjonalnymi mysliknikami) z suma kontrolna."""

    PATTERNS = [
        Pattern(
            name="NIP (10 digits, optional dashes)",
            regex=r"\b(?:\d{3}[-\s]?\d{3}[-\s]?\d{2}[-\s]?\d{2}|\d{10})\b",
            score=0.4,
        ),
    ]
    CONTEXT = ["nip", "NIP"]

    def __init__(self):
        super().__init__(
            supported_entity="PL_NIP",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="pl",
        )

    def validate_result(self, pattern_text: str) -> bool:
        digits = re.sub(r"[\s-]", "", pattern_text)
        if len(digits) != 10 or not digits.isdigit():
            return False
        weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
        s = sum(int(d) * w for d, w in zip(digits[:9], weights)) % 11
        return s != 10 and s == int(digits[9])


class REGONRecognizer(PatternRecognizer):
    """REGON - 9 lub 14 cyfr z suma kontrolna."""

    PATTERNS = [Pattern(name="REGON (9 or 14 digits)", regex=r"\b\d{9}(\d{5})?\b", score=0.3)]
    CONTEXT = ["regon", "REGON"]

    def __init__(self):
        super().__init__(
            supported_entity="PL_REGON",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="pl",
        )

    def validate_result(self, pattern_text: str) -> bool:
        if not pattern_text.isdigit():
            return False
        if len(pattern_text) == 9:
            weights = (8, 9, 2, 3, 4, 5, 6, 7)
            s = sum(int(d) * w for d, w in zip(pattern_text[:8], weights)) % 11
            check = 0 if s == 10 else s
            return check == int(pattern_text[8])
        if len(pattern_text) == 14:
            w9 = (8, 9, 2, 3, 4, 5, 6, 7)
            s9 = sum(int(d) * w for d, w in zip(pattern_text[:8], w9)) % 11
            check9 = 0 if s9 == 10 else s9
            if check9 != int(pattern_text[8]):
                return False
            w14 = (2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8)
            s14 = sum(int(d) * w for d, w in zip(pattern_text[:13], w14)) % 11
            check14 = 0 if s14 == 10 else s14
            return check14 == int(pattern_text[13])
        return False


class PolishIBANRecognizer(PatternRecognizer):
    """IBAN PL (PL + 26 cyfr) z walidacja mod-97."""

    PATTERNS = [
        Pattern(
            name="Polish IBAN",
            regex=r"\bPL[\s]?(?:\d[\s]?){26}\b",
            score=0.5,
        ),
    ]
    CONTEXT = ["iban", "IBAN", "konto", "rachunek"]

    def __init__(self):
        super().__init__(
            supported_entity="PL_IBAN",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="pl",
        )

    def validate_result(self, pattern_text: str) -> bool:
        cleaned = re.sub(r"\s", "", pattern_text).upper()
        if len(cleaned) != 28 or not cleaned.startswith("PL"):
            return False
        rearranged = cleaned[4:] + cleaned[:4]
        numeric = ""
        for ch in rearranged:
            if ch.isdigit():
                numeric += ch
            elif ch.isalpha():
                numeric += str(ord(ch) - 55)
            else:
                return False
        try:
            return int(numeric) % 97 == 1
        except ValueError:
            return False


class PolishIDCardRecognizer(PatternRecognizer):
    """Dowod osobisty PL - 3 litery + 6 cyfr (z checksum)."""

    PATTERNS = [
        Pattern(
            name="Polish ID card",
            regex=r"\b[A-Z]{3}\d{6}\b",
            score=0.4,
        ),
    ]
    CONTEXT = ["dowod", "dowod osobisty", "ID card"]

    _LETTER_VALUES = {chr(c): c - 55 for c in range(ord("A"), ord("Z") + 1)}

    def __init__(self):
        super().__init__(
            supported_entity="PL_ID_CARD",
            patterns=self.PATTERNS,
            context=self.CONTEXT,
            supported_language="pl",
        )

    def validate_result(self, pattern_text: str) -> bool:
        if len(pattern_text) != 9 or not pattern_text[:3].isalpha() or not pattern_text[3:].isdigit():
            return False
        weights = (7, 3, 1, 9, 7, 3, 1, 7, 3)
        values = [
            self._LETTER_VALUES[c] if c.isalpha() else int(c)
            for c in pattern_text.upper()
        ]
        # cyfra na pozycji 3 (czwarty znak) jest cyfra kontrolna
        check = (
            values[0] * weights[0]
            + values[1] * weights[1]
            + values[2] * weights[2]
            + values[4] * weights[4]
            + values[5] * weights[5]
            + values[6] * weights[6]
            + values[7] * weights[7]
            + values[8] * weights[8]
        ) % 10
        return check == values[3]


# ============================================================
#  Sekrety - klucze API, tokeny, klucze prywatne
# ============================================================
def _secret_recognizers() -> List[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="API_KEY_ANTHROPIC",
            supported_language="pl",
            patterns=[Pattern("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{30,}", 0.95)],
        ),
        PatternRecognizer(
            supported_entity="API_KEY_OPENAI",
            supported_language="pl",
            # Negative lookahead na 'ant-' - zeby nie lapac kluczy Anthropic, ktore tez
            # zaczynaja sie od 'sk-' (zostawiamy je dla bardziej specyficznego wzorca anthropic).
            patterns=[Pattern("OpenAI key", r"sk-(?!ant-)(?:proj-)?[A-Za-z0-9_\-]{30,}", 0.85)],
        ),
        PatternRecognizer(
            supported_entity="API_KEY_AWS",
            supported_language="pl",
            patterns=[Pattern("AWS access key id", r"\bAKIA[0-9A-Z]{16}\b", 0.95)],
        ),
        PatternRecognizer(
            supported_entity="API_KEY_GCP",
            supported_language="pl",
            patterns=[Pattern("GCP API key", r"\bAIza[0-9A-Za-z\-_]{35}\b", 0.9)],
        ),
        PatternRecognizer(
            supported_entity="GITHUB_TOKEN",
            supported_language="pl",
            patterns=[Pattern("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b", 0.95)],
        ),
        PatternRecognizer(
            supported_entity="SLACK_TOKEN",
            supported_language="pl",
            patterns=[Pattern("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", 0.9)],
        ),
        PatternRecognizer(
            supported_entity="JWT",
            supported_language="pl",
            patterns=[
                Pattern(
                    "JWT",
                    r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b",
                    0.85,
                )
            ],
        ),
        PatternRecognizer(
            supported_entity="PRIVATE_KEY",
            supported_language="pl",
            patterns=[
                Pattern(
                    "Private key block",
                    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                    0.99,
                )
            ],
        ),
        PatternRecognizer(
            supported_entity="PASSWORD_ASSIGNMENT",
            supported_language="pl",
            patterns=[
                Pattern(
                    "password=...",
                    r"(?i)(?:haslo|password|passwd|pwd)\s*[:=]\s*[\"']?([^\s\"',;]{6,})",
                    0.6,
                )
            ],
        ),
    ]


# ============================================================
#  Singleton AnalyzerEngine
# ============================================================
@dataclass(frozen=True)
class DlpFinding:
    entity_type: str
    start: int
    end: int
    score: float
    text: str


@lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    """Tworzy AnalyzerEngine z polskim spaCy NLP + custom recognizers."""
    nlp_configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "pl", "model_name": "pl_core_news_md"}],
    }
    provider = NlpEngineProvider(nlp_configuration=nlp_configuration)
    nlp_engine = provider.create_engine()

    registry = RecognizerRegistry(supported_languages=["pl"])

    # Wbudowane (jezyk-agnostyczne wzorce, rejestrujemy dla "pl")
    registry.add_recognizer(EmailRecognizer(supported_language="pl"))
    registry.add_recognizer(CreditCardRecognizer(supported_language="pl"))
    registry.add_recognizer(IpRecognizer(supported_language="pl"))
    registry.add_recognizer(UrlRecognizer(supported_language="pl"))
    registry.add_recognizer(PhoneRecognizer(supported_language="pl", supported_regions=["PL"]))

    # Polskie identyfikatory z checksum
    registry.add_recognizer(PESELRecognizer())
    registry.add_recognizer(NIPRecognizer())
    registry.add_recognizer(REGONRecognizer())
    registry.add_recognizer(PolishIBANRecognizer())
    registry.add_recognizer(PolishIDCardRecognizer())

    # Sekrety
    for r in _secret_recognizers():
        registry.add_recognizer(r)

    return AnalyzerEngine(
        nlp_engine=nlp_engine,
        registry=registry,
        supported_languages=["pl"],
    )


# ============================================================
#  API publiczne
# ============================================================
def analyze(text: str, score_threshold: float = 0.4) -> List[DlpFinding]:
    """Zwraca liste znalezisk PII/sekretow w tekscie (synchroniczne)."""
    analyzer = _get_analyzer()
    results = analyzer.analyze(
        text=text,
        language="pl",
        score_threshold=score_threshold,
    )
    return [
        DlpFinding(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            score=r.score,
            text=text[r.start:r.end],
        )
        for r in results
    ]


def redact(text: str, findings: List[DlpFinding]) -> str:
    """Podmienia znaleziska na placeholder [REDACTED:<typ>] od konca, zeby nie psuc offsetow.
    Wersja informacyjna - idzie do Claude, zachowuje typ wykrytego entytu."""
    if not findings:
        return text
    sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)
    out = text
    for f in sorted_findings:
        out = out[: f.start] + f"[REDACTED:{f.entity_type}]" + out[f.end :]
    return out


def redact_neutral(text: str, findings: List[DlpFinding]) -> str:
    """Wycina znaleziska BEZ tagow - tekst dla klasyfikatora.
    Tagi [REDACTED:TYP] zaburzaja semantyke (wielkie litery + dwukropek wygladaja jak adnotacje
    kodu, model NLI laczy je falszywie z etykietami typu 'kod oznaczony CONFIDENTIAL')."""
    if not findings:
        return text
    sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)
    out = text
    for f in sorted_findings:
        out = out[: f.start] + out[f.end :]
    return out


def warmup() -> None:
    """Wymusza inicjalizacje silnika (model spaCy + recognizery) - wywolaj przy starcie aplikacji."""
    _get_analyzer()
    logger.info("Presidio: silnik gotowy")
