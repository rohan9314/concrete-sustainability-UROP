"""In-memory store for saved TechnologyEvaluation objects."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from schemas.technology_evaluation import TechnologyEvaluation

_lock = threading.Lock()
_evaluations: dict[str, TechnologyEvaluation] = {}


def list_evaluations() -> list[TechnologyEvaluation]:
    with _lock:
        return list(_evaluations.values())


def get_evaluation(evaluation_id: str) -> TechnologyEvaluation | None:
    with _lock:
        return _evaluations.get(evaluation_id)


def save_evaluation(evaluation: TechnologyEvaluation) -> TechnologyEvaluation:
    timestamp = datetime.now(timezone.utc).isoformat()
    evaluation.metadata.updated_at = timestamp
    with _lock:
        _evaluations[evaluation.id] = evaluation
        return evaluation
