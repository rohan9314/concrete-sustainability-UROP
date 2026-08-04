"""Screening and LLM helpers for Cementitious Materials."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pipeline.concurrency import run_parallel_ordered
from pipeline.config import get_extraction_concurrency
from pipeline.llm_utils import DEFAULT_MODEL, InvalidJSONError, _parse_json_response
from pipeline.openai_client import call_openai
from pipeline.record_utils import record_dedupe_key
from pipeline.cementitious.prompts import (
    classification_system_prompt,
    classification_user_prompt,
    extraction_system_prompt,
    extraction_user_prompt,
    screening_system_prompt,
    screening_user_prompt,
)
from pipeline.cementitious.schema import (
    flatten_binder_components,
    normalize_record,
    new_record_id,
)
from pipeline.cementitious.taxonomy import Taxonomy, get_taxonomy
from pipeline.cementitious.evidence_alignment import align_record_evidence
from pipeline.year_utils import normalize_publication_year

logger = logging.getLogger(__name__)


def save_failed_llm_response(logs_dir: Path, *, name: str, raw: str) -> Path:
    path = logs_dir / "failed_llm_responses"
    path.mkdir(parents=True, exist_ok=True)
    out = path / f"{name}.txt"
    out.write_text(raw, encoding="utf-8")
    return out


def call_json_llm(
    *,
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    max_retries: int = 2,
    failed_dir: Path | None = None,
    fail_name: str = "failed",
) -> dict[str, Any]:
    from pipeline.cementitious.validation_metrics import get_call_metrics

    metrics = get_call_metrics()
    last_raw = ""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        metrics.record_llm_attempt()
        try:
            raw = call_openai(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            metrics.record_llm_failure(reason=str(exc))
            last_exc = exc
            logger.warning("LLM call failed (attempt %s): %s", attempt + 1, type(exc).__name__)
            continue
        last_raw = raw or ""
        try:
            parsed = _parse_json_response(last_raw)
            metrics.record_llm_success()
            return parsed
        except InvalidJSONError as exc:
            last_exc = exc
            metrics.record_llm_failure(reason=f"malformed_response:{exc}")
            logger.warning("Malformed LLM JSON (attempt %s): %s", attempt + 1, exc)
    if failed_dir is not None:
        save_failed_llm_response(failed_dir, name=fail_name, raw=last_raw)
    raise InvalidJSONError(str(last_exc) if last_exc else "invalid JSON")


def keyword_screen(
    record: dict[str, Any],
    index: int,
    *,
    taxonomy: Taxonomy,
    focus_sub_slugs: list[str] | None = None,
    focus_ss_slugs: list[str] | None = None,
) -> dict[str, Any]:
    paper_id = record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    text = f"{title}\n{abstract}".casefold()
    year, _ = normalize_publication_year(record)

    positive_terms: list[str] = []
    nodes = []
    if focus_ss_slugs:
        nodes = [taxonomy.sub_subcategories[s] for s in focus_ss_slugs if s in taxonomy.sub_subcategories]
    elif focus_sub_slugs:
        for s in focus_sub_slugs:
            nodes.append(taxonomy.subcategories[s])
            nodes.extend(taxonomy.children_of(s))
    else:
        nodes = taxonomy.all_nodes()
        positive_terms.extend(
            [
                "cement",
                "clinker",
                "scm",
                "pozzolan",
                "cementitious",
                "geopolymer",
                "alkali-activated",
                "carbon capture",
                "kiln",
            ]
        )

    for node in nodes:
        positive_terms.extend(t.casefold() for t in node.positive_screening_cues)
        positive_terms.extend(t.casefold() for t in node.retrieval_query_terms)
        positive_terms.extend(t.casefold() for t in node.representative_synonyms)

    negative_hits = []
    for node in nodes:
        for cue in node.negative_screening_cues:
            if cue.casefold() in text:
                negative_hits.append(cue)

    pos_hit = any(term in text for term in positive_terms if term)
    # If only negative aggregate/fuel framing and no cementitious use language, mark irrelevant
    aggregate_only = any(
        phrase in text
        for phrase in (
            "used as aggregate",
            "as aggregate only",
            "road base",
            "soil amendment",
        )
    )
    relevant = bool(pos_hit) and not (aggregate_only and "cement" not in text and "scm" not in text)
    return {
        "paper_id": paper_id,
        "title": title,
        "year": year or "",
        "doi": str(record.get("doi") or ""),
        "is_relevant": relevant,
        "confidence": "Medium" if relevant else "Low",
        "reason": "keyword heuristic grounded in taxonomy cues",
        "negative_match": "; ".join(negative_hits[:5]),
        "screening_mode": "keyword",
        "selected_subcategories": list(focus_sub_slugs or []),
        "selected_sub_subcategories": list(focus_ss_slugs or []),
    }


def llm_screen(
    record: dict[str, Any],
    index: int,
    *,
    taxonomy: Taxonomy,
    model: str = DEFAULT_MODEL,
    focus_sub_slugs: list[str] | None = None,
    focus_ss_slugs: list[str] | None = None,
    failed_dir: Path | None = None,
) -> dict[str, Any]:
    paper_id = record_dedupe_key(record) or f"paper:{index}"
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    year, _ = normalize_publication_year(record)
    scoped = bool(focus_sub_slugs or focus_ss_slugs)
    try:
        payload = call_json_llm(
            system=screening_system_prompt(scoped=scoped),
            user=screening_user_prompt(
                title=title,
                abstract=abstract,
                taxonomy=taxonomy,
                selected_sub_slugs=focus_sub_slugs,
                selected_ss_slugs=focus_ss_slugs,
            ),
            model=model,
            failed_dir=failed_dir,
            fail_name=f"screen_{index}",
        )
        return {
            "paper_id": paper_id,
            "title": title,
            "year": year or "",
            "doi": str(record.get("doi") or ""),
            "is_relevant": bool(payload.get("relevant")),
            "confidence": str(payload.get("relevance_confidence") or "Medium"),
            "reason": str(payload.get("reason") or ""),
            "negative_match": str(payload.get("negative_match") or ""),
            "suggested_technology_domain": payload.get("suggested_technology_domain") or "",
            "suggested_functional_role": payload.get("suggested_functional_role") or "",
            "screening_mode": "llm",
            "selected_subcategories": list(focus_sub_slugs or []),
            "selected_sub_subcategories": list(focus_ss_slugs or []),
        }
    except Exception as exc:
        from pipeline.cementitious.validation_metrics import get_call_metrics

        get_call_metrics().record_llm_fallback(reason=str(exc))
        logger.warning("LLM screen failed for %s: %s; falling back to keyword", paper_id, exc)
        row = keyword_screen(
            record,
            index,
            taxonomy=taxonomy,
            focus_sub_slugs=focus_sub_slugs,
            focus_ss_slugs=focus_ss_slugs,
        )
        row["screening_mode"] = "keyword_fallback"
        row["fallback_reason"] = str(exc)[:300]
        return row


def screen_records(
    records: list[dict[str, Any]],
    *,
    taxonomy: Taxonomy | None = None,
    keyword_only: bool = False,
    model: str = DEFAULT_MODEL,
    focus_sub_slugs: list[str] | None = None,
    focus_ss_slugs: list[str] | None = None,
    failed_dir: Path | None = None,
    concurrency: int | None = None,
) -> list[dict[str, Any]]:
    tax = taxonomy or get_taxonomy()

    def _one(idx_record: tuple[int, dict[str, Any]]) -> dict[str, Any]:
        idx, record = idx_record
        if keyword_only:
            return keyword_screen(
                record,
                idx,
                taxonomy=tax,
                focus_sub_slugs=focus_sub_slugs,
                focus_ss_slugs=focus_ss_slugs,
            )
        return llm_screen(
            record,
            idx,
            taxonomy=tax,
            model=model,
            focus_sub_slugs=focus_sub_slugs,
            focus_ss_slugs=focus_ss_slugs,
            failed_dir=failed_dir,
        )

    workers = concurrency or get_extraction_concurrency()
    indexed = list(enumerate(records))
    results = run_parallel_ordered(
        indexed,
        _one,
        concurrency=workers,
        label="cementitious_screen",
    )
    out: list[dict[str, Any]] = []
    for item in results:
        if item.success and isinstance(item.value, dict):
            out.append(item.value)
        else:
            idx, record = indexed[item.index]
            out.append(
                {
                    "paper_id": record_dedupe_key(record) or f"paper:{idx}",
                    "title": str(record.get("title") or ""),
                    "is_relevant": False,
                    "matched_subcategories": [],
                    "matched_sub_subcategories": [],
                    "confidence": "Low",
                    "reason": f"screening_error:{item.error or 'unknown'}",
                    "index": idx,
                }
            )
    return out


def heuristic_classify_and_extract(
    record: dict[str, Any],
    *,
    taxonomy: Taxonomy,
    selected_sub_slugs: list[str] | None = None,
    selected_ss_slugs: list[str] | None = None,
    source_type: str = "Literature",
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """
    Keyword/role-heuristic classification for dry local smoke tests (no LLM).

    Prefer LLM classification for production runs.
    """
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    text = f"{title}\n{abstract}".casefold()
    paper_id = record_dedupe_key(record) or new_record_id("src")
    year, _ = normalize_publication_year(record)

    candidates = list(taxonomy.sub_subcategories.values())
    if selected_ss_slugs:
        candidates = [taxonomy.sub_subcategories[s] for s in selected_ss_slugs if s in taxonomy.sub_subcategories]
    elif selected_sub_slugs:
        candidates = [c for s in selected_sub_slugs for c in taxonomy.children_of(s)]

    best = None
    best_score = 0
    for node in candidates:
        score = 0
        for term in list(node.representative_synonyms) + list(node.retrieval_query_terms) + list(
            node.representative_technology_variants
        ):
            t = term.casefold()
            if t and t in text:
                score += 2
        for cue in node.negative_screening_cues:
            if cue.casefold() in text:
                score -= 3
        if score > best_score:
            best_score = score
            best = node
    if best is None or best_score <= 0:
        return None, None
    parent = taxonomy.subcategories[taxonomy.parent_of_sub_sub[best.slug]]
    variant = best.representative_technology_variants[0] if best.representative_technology_variants else best.display_name
    row = normalize_record(
        {
            "category": taxonomy.category_display,
            "subcategory": parent.display_name,
            "subcategory_slug": parent.slug,
            "sub_subcategory": best.display_name,
            "sub_subcategory_slug": best.slug,
            "technology_variant": variant,
            "canonical_technology_name": variant,
            "raw_technology_name": title,
            "taxonomy_version": taxonomy.taxonomy_version,
            "taxonomy_confidence": "Low",
            "classification_basis": "Weakly Inferred",
            "classification_reasoning": (
                f"Heuristic match to {best.display_name} from title/abstract cues "
                "(keyword-only smoke mode; not for production)."
            ),
            "technology_domain": best.expected_technology_domain,
            "functional_role": best.allowed_functional_roles[0]
            if best.allowed_functional_roles
            else "Uncertain",
            "source_id": paper_id,
            "source_type": source_type,
            "source_title": title,
            "publication_year": year or "",
            "doi": record.get("doi") or "",
            "citation": str(record.get("doi") or paper_id),
            "evidence_text": abstract[:1000] or title,
            "extraction_confidence": "Low",
        },
        taxonomy=taxonomy,
    )
    source_for_evidence = "\n\n".join(
        part for part in (title, abstract) if str(part or "").strip()
    )
    align_record_evidence(
        row,
        source_text=source_for_evidence,
        content_source="literature_heuristic_title_abstract",
    )
    row = normalize_record(row, taxonomy=taxonomy)
    return row, None


def classify_and_extract(
    record: dict[str, Any],
    *,
    taxonomy: Taxonomy,
    model: str = DEFAULT_MODEL,
    selected_sub_slugs: list[str] | None = None,
    allow_proposals: bool = True,
    failed_dir: Path | None = None,
    source_type: str = "Literature",
    keyword_only: bool = False,
    selected_ss_slugs: list[str] | None = None,
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """
    Classify then extract one paper into zero-or-more cementitious records.

    Returns (primary_record_or_none, taxonomy_proposal_or_none).
    """
    if keyword_only:
        return heuristic_classify_and_extract(
            record,
            taxonomy=taxonomy,
            selected_sub_slugs=selected_sub_slugs,
            selected_ss_slugs=selected_ss_slugs,
            source_type=source_type,
        )

    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    body = str(record.get("text") or record.get("full_text") or "").strip()
    text = body or abstract
    paper_id = record_dedupe_key(record) or new_record_id("src")
    year, _ = normalize_publication_year(record)

    classification = call_json_llm(
        system=classification_system_prompt(),
        user=classification_user_prompt(
            taxonomy=taxonomy,
            title=title,
            text=text,
            selected_sub_slugs=selected_sub_slugs,
            allow_proposals=allow_proposals,
        ),
        model=model,
        failed_dir=failed_dir,
        fail_name=f"classify_{paper_id.replace(':', '_')}",
    )
    proposal = classification.get("taxonomy_proposal")
    if not classification.get("relevant"):
        return None, proposal if isinstance(proposal, dict) else None

    extraction = call_json_llm(
        system=extraction_system_prompt(),
        user=extraction_user_prompt(
            classification=classification,
            title=title,
            text=text,
            source_meta={
                "source_id": paper_id,
                "source_type": source_type,
                "doi": record.get("doi") or "",
                "publication_year": year or "",
            },
        ),
        model=model,
        failed_dir=failed_dir,
        fail_name=f"extract_{paper_id.replace(':', '_')}",
    )

    merged: dict[str, Any] = {}
    merged.update(extraction if isinstance(extraction, dict) else {})
    for key in (
        "subcategory",
        "subcategory_slug",
        "sub_subcategory",
        "sub_subcategory_slug",
        "technology_variant",
        "raw_technology_name",
        "canonical_technology_name",
        "taxonomy_confidence",
        "classification_basis",
        "classification_reasoning",
        "alternative_classification",
        "technology_domain",
        "functional_role",
    ):
        if classification.get(key) and not merged.get(key):
            merged[key] = classification[key]

    merged.setdefault("category", taxonomy.category_display)
    merged.setdefault("taxonomy_version", taxonomy.taxonomy_version)
    merged.setdefault("source_id", paper_id)
    merged.setdefault("source_type", source_type)
    merged.setdefault("source_title", title)
    merged.setdefault("publication_year", year or "")
    merged.setdefault("doi", record.get("doi") or "")
    if classification.get("evidence_span") and not merged.get("evidence_text"):
        merged["evidence_text"] = classification["evidence_span"]
    if isinstance(merged.get("binder_components"), list):
        merged.update(flatten_binder_components(merged["binder_components"]))

    # Prefer Academic Literature label for literature extracts.
    if str(merged.get("source_type") or "").strip() in ("", "Literature"):
        merged["source_type"] = "Academic Literature"

    normalized = normalize_record(merged, taxonomy=taxonomy)
    # Soft-drop unresolved without valid taxonomy assignment
    if normalized["classification_basis"] == "Unresolved" and not normalized["sub_subcategory_slug"]:
        return None, proposal if isinstance(proposal, dict) else None

    source_for_evidence = "\n\n".join(
        part for part in (title, abstract, body) if str(part or "").strip()
    )
    alignment = align_record_evidence(
        normalized,
        source_text=source_for_evidence,
        content_source="literature_title_abstract_or_full_text",
    )
    if (
        normalized.get("sub_subcategory_slug")
        and not alignment.taxonomy_supported
        and alignment.method == "taxonomy_unsupported"
    ):
        # Taxonomy-critical claim with no supporting span in source → drop record.
        return None, proposal if isinstance(proposal, dict) else None

    # Re-normalize after optional field clears from alignment
    normalized = normalize_record(normalized, taxonomy=taxonomy)
    return normalized, proposal if isinstance(proposal, dict) else None
