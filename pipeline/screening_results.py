"""Load screening results produced by run_ccs_abstract_screening.py."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.schema import AbstractScreeningResult


def load_screening_results(path: str | Path) -> tuple[dict, list[AbstractScreeningResult]]:
    """Load screening meta and result rows from a JSONL file."""
    file_path = Path(path)
    meta: dict = {}
    results: list[AbstractScreeningResult] = []

    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("type") == "screening_meta":
            meta = payload
            continue
        if "paper_id" in payload:
            results.append(AbstractScreeningResult.model_validate(payload))

    return meta, results


def relevant_paper_ids(path: str | Path) -> set[str]:
    """Return paper_ids marked is_relevant in a screening JSONL file."""
    _, results = load_screening_results(path)
    return {row.paper_id for row in results if row.is_relevant}
