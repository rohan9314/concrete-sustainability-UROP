"""SCM abstract screening (title + abstract only)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

from pipeline.concurrency import run_parallel_ordered
from pipeline.llm_utils import DEFAULT_MODEL, _parse_json_response
from pipeline.openai_client import call_openai
from pipeline.record_utils import record_dedupe_key
from pipeline.scm.prompts import DISCOVERY_SYSTEM_PROMPT, build_discovery_screening_prompt
from pipeline.scm.seed_categories import SCM_SEED_CATEGORIES, list_seed_category_ids
from pipeline.year_utils import normalize_publication_year

logger = logging.getLogger(__name__)

SCREENING_PROMPT_VERSION = "scm_abstract_screening_v1"


@dataclass
class ScmScreeningResult:
    paper_id: str
    title: str
    year: str
    doi: str
    is_relevant: bool
    confidence: float
    reason: str
    mentioned_materials: list[str]
    matched_seed_hints: list[str]
    prompt_version: str = SCREENING_PROMPT_VERSION

    def model_dump(self) -> dict:
        return asdict(self)


def _record_metadata(record: dict, index: int) -> tuple[str, str, str, str, str]:
    paper_id = record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip() or "Untitled paper"
    abstract = str(record.get("abstract") or "").strip()
    year, _ = normalize_publication_year(record)
    doi = str(record.get("doi") or "").strip()
    return paper_id, title, abstract, year or "NA", doi


def _keyword_screen(record: dict, index: int) -> ScmScreeningResult:
    paper_id, title, abstract, year, doi = _record_metadata(record, index)
    text = f"{title}\n{abstract}".lower()
    positive = (
        "supplementary cementitious",
        "scm",
        "pozzolan",
        "cement replacement",
        "clinker substitution",
        "fly ash",
        "slag cement",
        "silica fume",
        "metakaolin",
        "bottom ash",
        "glass powder",
        "ternary blend",
    )
    negative_only = (
        "glass fiber reinforced",
        "steel fiber",
        "pigment only",
    )
    is_relevant = any(term in text for term in positive) and not any(
        term in text for term in negative_only
    )
    hints = [
        slug
        for slug, name in SCM_SEED_CATEGORIES.items()
        if name.lower() in text or slug.replace("_", " ") in text
    ]
    return ScmScreeningResult(
        paper_id=paper_id,
        title=title,
        year=year,
        doi=doi,
        is_relevant=is_relevant,
        confidence=0.6 if is_relevant else 0.4,
        reason="keyword heuristic based on title and abstract only",
        mentioned_materials=[],
        matched_seed_hints=hints,
    )


def classify_record(
    record: dict,
    index: int,
    *,
    keyword_only: bool = False,
    model: str = DEFAULT_MODEL,
) -> ScmScreeningResult:
    if keyword_only:
        return _keyword_screen(record, index)

    paper_id, title, abstract, year, doi = _record_metadata(record, index)
    prompt = build_discovery_screening_prompt(title=title, abstract=abstract)
    try:
        raw = call_openai(
            model=model,
            messages=[
                {"role": "system", "content": DISCOVERY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        payload = _parse_json_response(raw)
    except Exception as exc:
        logger.warning("SCM screening LLM failed for %s: %s", paper_id, exc)
        return _keyword_screen(record, index)

    is_relevant = bool(payload.get("is_relevant"))
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    materials = payload.get("mentioned_materials") or []
    if not isinstance(materials, list):
        materials = []
    return ScmScreeningResult(
        paper_id=paper_id,
        title=title,
        year=year,
        doi=doi,
        is_relevant=is_relevant,
        confidence=max(0.0, min(1.0, confidence)),
        reason=str(payload.get("reason") or ""),
        mentioned_materials=[str(m) for m in materials],
        matched_seed_hints=[
            slug
            for slug in list_seed_category_ids()
            if slug in json.dumps(materials).lower()
        ],
    )


def classify_records_parallel(
    records: list[dict],
    *,
    start_index: int = 0,
    keyword_only: bool = False,
    concurrency: int | None = None,
) -> list[ScmScreeningResult]:
    from pipeline.config import get_extraction_concurrency

    workers = concurrency or get_extraction_concurrency()

    def _one(item: tuple[int, dict]) -> ScmScreeningResult:
        offset, record = item
        return classify_record(
            record,
            start_index + offset,
            keyword_only=keyword_only,
        )

    indexed = list(enumerate(records))
    parallel = run_parallel_ordered(
        indexed,
        _one,
        concurrency=workers,
        label="scm_screening",
    )
    results: list[ScmScreeningResult] = []
    for item in parallel:
        if item.success and item.value is not None:
            results.append(item.value)
        else:
            offset, record = item.item
            results.append(
                classify_record(
                    record,
                    start_index + offset,
                    keyword_only=True,
                ),
            )
    return results
