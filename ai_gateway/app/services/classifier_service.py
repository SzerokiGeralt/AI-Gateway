"""
DLP - warstwa 2: klasyfikacja tematyczna przez embedding similarity.

Lokalny encoder (sentence-transformers, multilingual MiniLM) liczy embeddingi
prompt + etykiet zakazanych tematow z polityki, porownuje przez cosine similarity.
W przeciwienstwie do zero-shot NLI: deterministyczne, brak halucynacji,
score odzwierciedla rzeczywista bliskosc semantyczna.

Komponent jest synchroniczny - wywolania z asyncio uruchamiaj przez
asyncio.to_thread, zeby nie blokowac event loopa.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    is_violation: bool
    matched_label: str | None
    score: float
    all_scores: dict[str, float]


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    model_name = settings.DLP_CLASSIFIER_MODEL
    logger.info("Klasyfikator DLP: laduje encoder %s", model_name)
    return SentenceTransformer(model_name, device="cpu")


@lru_cache(maxsize=8)
def _embed_labels(labels: Tuple[str, ...]) -> np.ndarray:
    """
    Cache embeddingow etykiet polityki - polityka zmienia sie rzadko,
    encode trwa ~50-200 ms na ~10 etykiet, niewarto liczyc przy kazdym requeście.
    """
    model = _get_model()
    return model.encode(
        list(labels),
        normalize_embeddings=True,
        convert_to_numpy=True,
    )


def classify(
    text: str,
    candidate_labels: List[str],
    threshold: float | None = None,
) -> ClassificationResult:
    """
    Liczy cosine similarity miedzy promptem a kazda etykieta z polityki.
    Zwraca ClassificationResult; is_violation=True gdy najlepsza etykieta
    przekracza prog (settings.DLP_CLASSIFIER_THRESHOLD jesli nie podano).
    """
    if not candidate_labels:
        return ClassificationResult(False, None, 0.0, {})
    if not text.strip():
        return ClassificationResult(False, None, 0.0, {})

    th = threshold if threshold is not None else settings.DLP_CLASSIFIER_THRESHOLD

    model = _get_model()
    text_emb = model.encode(
        text,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    label_embs = _embed_labels(tuple(candidate_labels))

    # normalize_embeddings=True -> dot product = cosine similarity
    sims = label_embs @ text_emb  # shape: (N,)
    all_scores = {label: float(score) for label, score in zip(candidate_labels, sims)}

    top_idx = int(np.argmax(sims))
    top_label = candidate_labels[top_idx]
    top_score = float(sims[top_idx])

    if top_score >= th:
        return ClassificationResult(True, top_label, top_score, all_scores)
    return ClassificationResult(False, None, top_score, all_scores)


def warmup() -> None:
    """Wymusza zaladowanie encodera - wywolaj przy starcie aplikacji."""
    _get_model()
    logger.info("Klasyfikator DLP: gotowy")
