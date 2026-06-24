"""
Stage 1: LLM abstract screening for CCS subpath relevance.

Classifies papers using only title and abstract — never full paper text.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from dotenv import load_dotenv

from openai_flex import call_openai_flex  # noqa: E402
from llm import DEFAULT_MODEL, _parse_json_response  # noqa: E402
from pipeline.screening import (
    CCS_SUBPATHS,
    CCS_SUBPATH_DESCRIPTIONS,
    coerce_confidence,
    get_screening_text,
    normalize_subpaths,
)
from pipeline.schema import AbstractScreeningResult, NOT_REPORTED
from pipeline.year_utils import normalize_publication_year

load_dotenv()
logger = logging.getLogger(__name__)

SCREENING_PROMPT_VERSION = "ccs_abstract_screening_v1"

SCREENING_SYSTEM_PROMPT = f"""You screen scientific papers for relevance to carbon capture and storage (CCS)
technologies applied to cement production or cement kiln emissions.

You receive ONLY a paper title and abstract. You do NOT have access to the full paper text.
Base every decision strictly on the title and abstract provided.
Do not infer details that are not supported by the title or abstract.

Classify whether the paper is relevant to cement/concrete CCS decarbonization and which CCS
subpaths apply. A paper may match multiple subpaths.

Allowed subpath identifiers (use exactly these strings):
{json.dumps(CCS_SUBPATHS)}

Subpath meanings:
{json.dumps(CCS_SUBPATH_DESCRIPTIONS, indent=2)}

Return valid JSON only with this schema:
{{
  "is_relevant": true or false,
  "relevant_subpaths": ["calcium_looping", "..."],
  "confidence": 0.0 to 1.0,
  "reason": "brief explanation citing only the title and abstract"
}}

Rules:
- is_relevant=true only if the paper discusses CCS capture technology for cement, cement kilns,
  clinker production, or cement plant CO2 emissions (not generic concrete durability alone).
- If is_relevant=false, relevant_subpaths must be [].
- If is_relevant=true, include every matching subpath from the allowed list.
- confidence reflects how clearly the title/abstract support the classification.
- reason must state it is based on the title and abstract only.
"""


@dataclass
class ClassifierOptions:
    model: str = DEFAULT_MODEL
    prompt_version: str = SCREENING_PROMPT_VERSION
    keyword_only: bool = False


def _record_metadata(record: dict, index: int) -> tuple[str, str, str, str, str]:
    from paper_records import _record_dedupe_key  # noqa: E402

    paper_id = _record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip() or "Untitled paper"
    abstract = str(record.get("abstract") or "").strip()
    year, _ = normalize_publication_year(record)
    doi = str(record.get("doi") or "").strip()
    return paper_id, title, abstract, year or NOT_REPORTED, doi


def _keyword_screen(record: dict, index: int) -> AbstractScreeningResult:
    """Offline heuristic fallback for tests without API calls."""
    from pipeline.query_scoring import QueryContext, score_query

    paper_id, title, abstract, year, doi = _record_metadata(record, index)
    screening = get_screening_text(record).lower()
    matched_subpaths: list[str] = []
    best_score = 0.0

    slug_map = {
        "chemical absorption": "chemical_absorption",
        "cryogenic processes": "cryogenic_processes",
        "oxy-fuel combustion": "oxy_fuel_combustion",
        "membrane separation": "membrane_separation",
        "calcium looping": "calcium_looping",
        "direct separation": "direct_separation",
    }

    for tech_name, subpath in slug_map.items():
        context = QueryContext(technology_name=tech_name)
        result = score_query(screening, context)
        if result.query_score >= 4.0:
            matched_subpaths.append(subpath)
            best_score = max(best_score, result.query_score)

    cement_terms = ("cement", "kiln", "clinker", "carbon capture", "ccs", "co2")
    has_cement = any(term in screening for term in cement_terms)
    is_relevant = bool(matched_subpaths) and has_cement
    confidence = min(1.0, best_score / 15.0) if is_relevant else 0.0

    if is_relevant:
        reason = (
            f"Based on the title and abstract, matched CCS subpaths: {', '.join(matched_subpaths)}."
        )
    else:
        reason = "Based on the title and abstract, no clear cement CCS subpath relevance."

    return AbstractScreeningResult(
        paper_id=paper_id,
        index=index,
        title=title,
        abstract=abstract,
        year=year,
        doi=doi,
        is_relevant=is_relevant,
        relevant_subpaths=matched_subpaths,
        confidence=round(confidence, 3),
        reason=reason,
    )


def classify_record(
    record: dict,
    index: int,
    *,
    options: ClassifierOptions | None = None,
) -> AbstractScreeningResult:
    """Classify one paper using title+abstract screening."""
    opts = options or ClassifierOptions()
    paper_id, title, abstract, year, doi = _record_metadata(record, index)

    if opts.keyword_only:
        return _keyword_screen(record, index)

    screening_text = get_screening_text(record)
    user_prompt = (
        "Screen this paper for cement/concrete CCS relevance.\n\n"
        f"{screening_text}\n\n"
        "Remember: use only the title and abstract above."
    )

    try:
        raw = call_openai_flex(
            model=opts.model,
            messages=[
                {"role": "system", "content": SCREENING_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = _parse_json_response(raw)

        subpaths = normalize_subpaths(data.get("relevant_subpaths"))
        is_relevant = bool(data.get("is_relevant")) and bool(subpaths)
        if bool(data.get("is_relevant")) and not subpaths:
            is_relevant = False

        reason = str(data.get("reason") or "").strip()
        if reason and "abstract" not in reason.lower():
            reason = f"{reason} (based on title and abstract only.)"
        if not reason:
            reason = "Classification based on title and abstract only."

        return AbstractScreeningResult(
            paper_id=paper_id,
            index=index,
            title=title,
            abstract=abstract,
            year=year,
            doi=doi,
            is_relevant=is_relevant,
            relevant_subpaths=subpaths,
            confidence=coerce_confidence(data.get("confidence")),
            reason=reason,
        )
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        logger.warning("classify_record failed for %s: %s", paper_id, message)
        return AbstractScreeningResult(
            paper_id=paper_id,
            index=index,
            title=title,
            abstract=abstract,
            year=year,
            doi=doi,
            is_relevant=False,
            relevant_subpaths=[],
            confidence=0.0,
            reason=f"Screening failed: {message}",
        )


def classify_records_parallel(
    records: list[dict],
    *,
    start_index: int = 0,
    options: ClassifierOptions | None = None,
    concurrency: int | None = None,
) -> list[AbstractScreeningResult]:
    """Run bounded parallel abstract screening."""
    from concurrency import run_parallel_ordered  # noqa: E402
    from pipeline.config import get_extraction_concurrency

    opts = options or ClassifierOptions()
    limit = concurrency or get_extraction_concurrency()

    indexed = list(enumerate(records, start=start_index))

    def worker(item: tuple[int, dict]) -> AbstractScreeningResult:
        index, record = item
        return classify_record(record, index, options=opts)

    parallel = run_parallel_ordered(indexed, worker, concurrency=limit, label="ccs_abstract_screening")
    results: list[AbstractScreeningResult] = []
    for item in parallel:
        if item.success and item.value is not None:
            results.append(item.value)
        else:
            index, record = indexed[item.index]
            paper_id, title, abstract, year, doi = _record_metadata(record, index)
            results.append(
                AbstractScreeningResult(
                    paper_id=paper_id,
                    index=index,
                    title=title,
                    abstract=abstract,
                    year=year,
                    doi=doi,
                    is_relevant=False,
                    relevant_subpaths=[],
                    confidence=0.0,
                    reason=item.error or "Screening worker failed",
                ),
            )
    return results
