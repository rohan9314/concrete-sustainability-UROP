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
from pipeline.cementitious.decarb_literature import (
    heuristic_classify_canonical,
    keyword_screen_canonical,
    literature_uses_canonical_taxonomy,
    match_level1_labels,
    parse_classification_paths,
)
from pipeline.cementitious.prompts import (
    canonical_classification_system_prompt,
    canonical_classification_user_prompt,
    canonical_screening_system_prompt,
    canonical_screening_user_prompt,
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
    if literature_uses_canonical_taxonomy(
        focus_sub_slugs=focus_sub_slugs,
        focus_ss_slugs=focus_ss_slugs,
    ):
        return keyword_screen_canonical(record, index)
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
    canonical = literature_uses_canonical_taxonomy(
        focus_sub_slugs=focus_sub_slugs,
        focus_ss_slugs=focus_ss_slugs,
    )
    try:
        if canonical:
            system = canonical_screening_system_prompt()
            user = canonical_screening_user_prompt(title=title, abstract=abstract)
        else:
            system = screening_system_prompt(scoped=scoped)
            user = screening_user_prompt(
                title=title,
                abstract=abstract,
                taxonomy=taxonomy,
                selected_sub_slugs=focus_sub_slugs,
                selected_ss_slugs=focus_ss_slugs,
            )
        payload = call_json_llm(
            system=system,
            user=user,
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
            "suggested_level_1": payload.get("suggested_level_1") or [],
            "screening_mode": "llm",
            "literature_taxonomy": "canonical" if canonical else "runtime",
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


def _backfill_runtime_assignment(row: dict[str, Any], taxonomy: Taxonomy) -> dict[str, Any]:
    """Fill 9×58 slugs from a canonical path when the node is cementitious."""
    if row.get("sub_subcategory_slug"):
        return row
    from pipeline.cementitious.decarbonization_taxonomy import get_decarbonization_taxonomy
    from pipeline.cementitious.paths import is_taxonomy_na
    from pipeline.cementitious.taxonomy_migration import runtime_assignment_for_decarb_node

    labels = [
        str(row.get(f"taxonomy_level_{i}") or "")
        for i in range(5)
        if str(row.get(f"taxonomy_level_{i}") or "")
        and not is_taxonomy_na(str(row.get(f"taxonomy_level_{i}") or ""))
    ]
    if len(labels) < 2:
        return row
    try:
        node = get_decarbonization_taxonomy().resolve_path_labels(labels)
    except ValueError:
        return row
    assignment = runtime_assignment_for_decarb_node(node, runtime=taxonomy)
    if assignment:
        for key, value in assignment.items():
            if not row.get(key):
                row[key] = value
    return row


def _record_from_canonical_path(
    record: dict[str, Any],
    path: dict[str, str],
    *,
    taxonomy: Taxonomy,
    source_type: str,
    paper_id: str,
    year: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, str]:
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    payload = {
        "category": path.get("taxonomy_level_1") or "",
        "taxonomy_level_0": path.get("taxonomy_level_0") or "Concrete Decarbonization",
        "taxonomy_level_1": path.get("taxonomy_level_1") or "",
        "taxonomy_level_2": path.get("taxonomy_level_2") or "N.A.",
        "taxonomy_level_3": path.get("taxonomy_level_3") or "N.A.",
        "taxonomy_level_4": path.get("taxonomy_level_4") or "N.A.",
        "technology_variant": (extra or {}).get("technology_variant")
        or (
            path.get("taxonomy_level_4")
            if path.get("taxonomy_level_4") not in {"", "N.A."}
            else path.get("taxonomy_level_3") or title
        ),
        "canonical_technology_name": (extra or {}).get("canonical_technology_name")
        or path.get("taxonomy_level_4")
        or path.get("taxonomy_level_3")
        or title,
        "raw_technology_name": (extra or {}).get("raw_technology_name") or title,
        "taxonomy_version": taxonomy.taxonomy_version,
        "taxonomy_confidence": path.get("taxonomy_confidence") or "Low",
        "classification_basis": path.get("classification_basis") or "Weakly Inferred",
        "classification_reasoning": path.get("classification_reasoning")
        or "Canonical taxonomy classification.",
        "source_id": paper_id,
        "source_type": source_type,
        "source_title": title,
        "publication_year": year or "",
        "doi": record.get("doi") or "",
        "citation": str(record.get("doi") or paper_id),
        "evidence_text": (extra or {}).get("evidence_text") or abstract[:1000] or title,
        "extraction_confidence": (extra or {}).get("extraction_confidence") or "Low",
        "record_id": new_record_id("cm"),
    }
    if extra:
        for key, value in extra.items():
            if value and key not in payload:
                payload[key] = value
    payload = _backfill_runtime_assignment(payload, taxonomy)
    return normalize_record(payload, taxonomy=taxonomy)


def _finalize_extracted_row(
    row: dict[str, str],
    *,
    taxonomy: Taxonomy,
    title: str,
    abstract: str,
    body: str = "",
    content_source: str,
) -> dict[str, str] | None:
    row = _backfill_runtime_assignment(row, taxonomy)
    row = normalize_record(row, taxonomy=taxonomy)
    has_canonical = bool(row.get("taxonomy_level_1")) and row.get("taxonomy_level_1") not in {
        "",
        "N.A.",
    }
    if row["classification_basis"] == "Unresolved" and not row["sub_subcategory_slug"] and not has_canonical:
        return None
    source_for_evidence = "\n\n".join(
        part for part in (title, abstract, body) if str(part or "").strip()
    )
    alignment = align_record_evidence(
        row,
        source_text=source_for_evidence,
        content_source=content_source,
    )
    if (
        row.get("sub_subcategory_slug")
        and not alignment.taxonomy_supported
        and alignment.method == "taxonomy_unsupported"
    ):
        return None
    return normalize_record(row, taxonomy=taxonomy)


def heuristic_classify_and_extract(
    record: dict[str, Any],
    *,
    taxonomy: Taxonomy,
    selected_sub_slugs: list[str] | None = None,
    selected_ss_slugs: list[str] | None = None,
    source_type: str = "Literature",
) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    rows, proposal = heuristic_classify_and_extract_records(
        record,
        taxonomy=taxonomy,
        selected_sub_slugs=selected_sub_slugs,
        selected_ss_slugs=selected_ss_slugs,
        source_type=source_type,
    )
    return (rows[0] if rows else None), proposal


def heuristic_classify_and_extract_records(
    record: dict[str, Any],
    *,
    taxonomy: Taxonomy,
    selected_sub_slugs: list[str] | None = None,
    selected_ss_slugs: list[str] | None = None,
    source_type: str = "Literature",
) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    """
    Keyword/role-heuristic classification for dry local smoke tests (no LLM).

    Prefer LLM classification for production runs. Canonical mode may return
    multiple records when a paper spans more than one Level-1 branch.
    """
    if literature_uses_canonical_taxonomy(
        focus_sub_slugs=selected_sub_slugs,
        focus_ss_slugs=selected_ss_slugs,
    ):
        title = str(record.get("title") or "").strip()
        abstract = str(record.get("abstract") or "").strip()
        paper_id = record_dedupe_key(record) or new_record_id("src")
        year, _ = normalize_publication_year(record)
        paths = heuristic_classify_canonical(record)
        rows: list[dict[str, str]] = []
        for path in paths:
            row = _record_from_canonical_path(
                record,
                path,
                taxonomy=taxonomy,
                source_type=source_type,
                paper_id=paper_id,
                year=year or "",
            )
            finalized = _finalize_extracted_row(
                row,
                taxonomy=taxonomy,
                title=title,
                abstract=abstract,
                content_source="literature_heuristic_title_abstract",
            )
            if finalized:
                rows.append(finalized)
        if len(rows) > 1:
            ids = [r.get("record_id") or "" for r in rows]
            for row in rows:
                row["related_record_ids"] = ";".join(x for x in ids if x and x != row.get("record_id"))
        return rows, None

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
        return [], None
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
    finalized = _finalize_extracted_row(
        row,
        taxonomy=taxonomy,
        title=title,
        abstract=abstract,
        content_source="literature_heuristic_title_abstract",
    )
    return ([finalized] if finalized else []), None


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
    Classify then extract one paper into zero-or-more records.

    Returns (primary_record_or_none, taxonomy_proposal_or_none).
    Multi-branch papers emit additional records via ``classify_and_extract_records``.
    """
    rows, proposal = classify_and_extract_records(
        record,
        taxonomy=taxonomy,
        model=model,
        selected_sub_slugs=selected_sub_slugs,
        allow_proposals=allow_proposals,
        failed_dir=failed_dir,
        source_type=source_type,
        keyword_only=keyword_only,
        selected_ss_slugs=selected_ss_slugs,
    )
    return (rows[0] if rows else None), proposal


def classify_and_extract_records(
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
) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    """Classify then extract. One canonical path per record; multiple paths → multiple records."""
    if keyword_only:
        return heuristic_classify_and_extract_records(
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
    canonical = literature_uses_canonical_taxonomy(
        focus_sub_slugs=selected_sub_slugs,
        focus_ss_slugs=selected_ss_slugs,
    )

    if canonical:
        l1_hint = match_level1_labels(f"{title}\n{abstract}".casefold())
        classification = call_json_llm(
            system=canonical_classification_system_prompt(),
            user=canonical_classification_user_prompt(
                title=title,
                text=text,
                level_1_labels=l1_hint,
            ),
            model=model,
            failed_dir=failed_dir,
            fail_name=f"classify_{paper_id.replace(':', '_')}",
        )
    else:
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
    proposal_dict = proposal if isinstance(proposal, dict) else None
    if not classification.get("relevant"):
        return [], proposal_dict

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
        "taxonomy_level_0",
        "taxonomy_level_1",
        "taxonomy_level_2",
        "taxonomy_level_3",
        "taxonomy_level_4",
    ):
        if classification.get(key) and not merged.get(key):
            merged[key] = classification[key]

    merged.setdefault("category", merged.get("taxonomy_level_1") or taxonomy.category_display)
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
    if str(merged.get("source_type") or "").strip() in ("", "Literature"):
        merged["source_type"] = "Academic Literature"

    paths = parse_classification_paths(classification)
    if not paths:
        paths = parse_classification_paths(merged)
    rows: list[dict[str, str]] = []
    if paths:
        for path in paths:
            payload = dict(merged)
            payload.update(path)
            payload["record_id"] = new_record_id("cm")
            payload = _backfill_runtime_assignment(payload, taxonomy)
            normalized = normalize_record(payload, taxonomy=taxonomy)
            finalized = _finalize_extracted_row(
                normalized,
                taxonomy=taxonomy,
                title=title,
                abstract=abstract,
                body=body,
                content_source="literature_title_abstract_or_full_text",
            )
            if finalized:
                rows.append(finalized)
    else:
        normalized = normalize_record(merged, taxonomy=taxonomy)
        finalized = _finalize_extracted_row(
            normalized,
            taxonomy=taxonomy,
            title=title,
            abstract=abstract,
            body=body,
            content_source="literature_title_abstract_or_full_text",
        )
        if finalized:
            rows.append(finalized)
    if len(rows) > 1:
        ids = [r.get("record_id") or "" for r in rows]
        for row in rows:
            row["related_record_ids"] = ";".join(x for x in ids if x and x != row.get("record_id"))
    return rows, proposal_dict
