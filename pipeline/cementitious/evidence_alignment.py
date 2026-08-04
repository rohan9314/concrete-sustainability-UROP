"""Deterministic evidence-span alignment for cementitious extraction.

Ensures stored ``evidence_text`` contains the passage that actually supports
taxonomy-critical and numeric claims. Prefers span search over extra LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# Taxonomy-critical support terms by sub_subcategory slug.
# Extend here rather than hard-coding one-off checks in extraction branches.
TAXONOMY_EVIDENCE_TERMS: dict[str, tuple[str, ...]] = {
    "chemical_absorption": (
        "chemical absorption",
        "solvent absorption",
        "solvent-based capture",
        "solvent based capture",
        "post-combustion solvent",
        "post combustion solvent",
        "amine scrubbing",
        "amine absorption",
        "amine-based",
        "amine based",
        "amines",
        "amine",
        "monoethanolamine",
        "mea",
        "absorption column",
        "absorber",
        "solvent capture",
    ),
    "oxy_fuel_combustion": (
        "oxy-fuel",
        "oxyfuel",
        "oxy fuel",
        "oxygen-enriched combustion",
    ),
    "calcium_looping": (
        "calcium looping",
        "ca-looping",
        "calcium looping process",
        "cao looping",
    ),
    "membrane_separation": (
        "membrane separation",
        "membrane capture",
        "gas separation membrane",
    ),
    "cryogenic_carbon_capture": (
        "cryogenic",
        "cryogenic capture",
        "low-temperature separation",
    ),
    "direct_separation": (
        "direct separation",
        "indirect calcination",
        "leilac",
    ),
}

# Optional numeric / binder fields that must be grounded when populated.
NUMERIC_EVIDENCE_FIELDS: tuple[str, ...] = (
    "cement_replacement_percentage",
    "cement_replacement_min_percentage",
    "cement_replacement_max_percentage",
    "clinker_reduction_percentage",
    "optimum_replacement_percentage",
    "compressive_strength_value",
    "compressive_strength_change_percentage",
    "strength_activity_index",
    "co2_reduction_value",
    "co2_reduction_percentage",
    "embodied_carbon_value",
    "carbon_capture_rate",
    "carbon_capture_capacity",
    "co2_purity_percentage",
    "energy_penalty_value",
    "process_temperature",
    "cost_value",
    "binder_component_1_fraction",
    "binder_component_2_fraction",
    "binder_component_3_fraction",
    "binder_component_4_fraction",
    "water_binder_ratio",
    "testing_age_days",
)

UNIT_FIELD_PAIRS: tuple[tuple[str, str], ...] = (
    ("compressive_strength_value", "compressive_strength_unit"),
    ("co2_reduction_value", "co2_reduction_unit"),
    ("embodied_carbon_value", "embodied_carbon_unit"),
    ("carbon_capture_capacity", "carbon_capture_capacity_unit"),
    ("energy_penalty_value", "energy_penalty_unit"),
    ("process_temperature", "process_temperature_unit"),
    ("cost_value", "cost_unit"),
)

# Generic CCS phrases that are NOT sufficient alone for Chemical Absorption.
GENERIC_CCS_ONLY_TERMS: tuple[str, ...] = (
    "carbon capture",
    "ccs",
    "ccus",
    "captured co2",
    "captured carbon",
    "cement decarbonization",
    "decarbonising",
    "decarbonizing",
)


@dataclass
class EvidenceAlignmentResult:
    evidence_text: str
    method: str
    reason: str
    cleared_fields: list[str]
    taxonomy_supported: bool
    source_window_used: str = ""


def _normalize_for_match(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("％", "%")
    text = re.sub(r"\s+", " ", text)
    return text


def _casefold_norm(text: str) -> str:
    return _normalize_for_match(text).casefold()


def _number_patterns(value: str) -> list[str]:
    """Formatting variants for a numeric claim (matching only)."""
    raw = str(value or "").strip()
    if not raw:
        return []
    nums = re.findall(r"-?\d+(?:\.\d+)?", raw)
    patterns: list[str] = []
    for n in nums:
        patterns.extend(
            [
                n,
                f"{n}%",
                f"{n} %",
                f"{n} percent",
                f"{n} per cent",
                n.replace(".", ","),
                f"{n.replace('.', ',')}%",
            ]
        )
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in patterns:
        key = p.casefold()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def split_candidate_spans(source_text: str, *, max_span_chars: int = 600) -> list[str]:
    """Split source text into paragraph / sentence windows."""
    text = _normalize_for_match(source_text)
    if not text:
        return []
    parts = re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    spans: list[str] = []
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        if len(chunk) <= max_span_chars:
            spans.append(chunk)
            continue
        # Sliding windows for long paragraphs
        step = max(80, max_span_chars // 2)
        for i in range(0, len(chunk), step):
            window = chunk[i : i + max_span_chars].strip()
            if window:
                spans.append(window)
    # Also keep a few overlapping sentence pairs for numeric+material proximity
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    for i in range(len(sentences) - 1):
        pair = f"{sentences[i]} {sentences[i + 1]}".strip()
        if 40 < len(pair) <= max_span_chars * 2:
            spans.append(pair[: max_span_chars * 2])
    return spans


def taxonomy_support_terms(sub_subcategory_slug: str) -> tuple[str, ...]:
    return TAXONOMY_EVIDENCE_TERMS.get((sub_subcategory_slug or "").strip(), ())


def span_has_taxonomy_support(span: str, sub_subcategory_slug: str) -> bool:
    terms = taxonomy_support_terms(sub_subcategory_slug)
    if not terms:
        return True
    blob = _casefold_norm(span)
    for term in terms:
        t = term.casefold()
        if len(t) <= 3:
            # short tokens (e.g. MEA): word-boundary match
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", blob):
                return True
        elif t in blob:
            return True
    return False


def score_span_for_taxonomy(span: str, sub_subcategory_slug: str) -> int:
    terms = taxonomy_support_terms(sub_subcategory_slug)
    if not terms:
        return 0
    blob = _casefold_norm(span)
    score = 0
    for term in terms:
        t = term.casefold()
        if len(t) <= 3:
            if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", blob):
                score += 5
        elif t in blob:
            score += 3 + min(4, len(t) // 8)
    # Penalize generic-only CCS chatter without absorption terms
    if score == 0 and any(g in blob for g in GENERIC_CCS_ONLY_TERMS):
        score -= 1
    # Prefer shorter complete spans
    if score > 0:
        score += max(0, 8 - len(span) // 120)
    return score


def find_best_taxonomy_span(
    source_text: str,
    sub_subcategory_slug: str,
    *,
    preferred: str = "",
) -> str:
    """Return the best supporting span, or empty if none found."""
    if not taxonomy_support_terms(sub_subcategory_slug):
        return (preferred or source_text[:500]).strip()
    candidates = []
    if preferred and preferred.strip():
        candidates.append(preferred.strip())
    candidates.extend(split_candidate_spans(source_text))
    best = ""
    best_score = 0
    for span in candidates:
        score = score_span_for_taxonomy(span, sub_subcategory_slug)
        if score > best_score:
            best_score = score
            best = span
    return best if best_score > 0 else ""


def span_supports_numeric_value(
    span: str,
    value: str,
    *,
    unit: str = "",
    context_terms: Iterable[str] = (),
) -> bool:
    blob = _casefold_norm(span)
    patterns = _number_patterns(value)
    if not patterns:
        return False
    if not any(p.casefold() in blob for p in patterns):
        return False
    if unit and str(unit).strip():
        u = str(unit).strip().casefold()
        # percent-like units are covered by number patterns
        if u not in {"%", "percent", "pct", "percentage"} and u not in blob:
            return False
    ctx = [t for t in context_terms if t and len(str(t).strip()) >= 3]
    if ctx:
        hits = sum(1 for t in ctx if str(t).casefold() in blob)
        if hits < 1:
            return False
    return True


def find_best_numeric_span(
    source_text: str,
    value: str,
    *,
    unit: str = "",
    context_terms: Iterable[str] = (),
    preferred: str = "",
) -> str:
    candidates: list[str] = []
    if preferred and preferred.strip():
        candidates.append(preferred.strip())
    candidates.extend(split_candidate_spans(source_text))
    best = ""
    best_len = 10**9
    for span in candidates:
        if not span_supports_numeric_value(
            span, value, unit=unit, context_terms=context_terms
        ):
            continue
        if len(span) < best_len:
            best = span
            best_len = len(span)
    return best


def _nonempty(value: Any) -> bool:
    return str(value or "").strip() not in ("", "None", "null", "nan")


def _context_terms_for_field(record: dict[str, Any], field: str) -> list[str]:
    terms: list[str] = []
    if field.startswith("binder_component_"):
        # binder_component_1_fraction → binder_component_1
        base = field.replace("_fraction", "")
        name = record.get(base) or ""
        if name:
            terms.append(str(name))
        for key in (
            "raw_technology_name",
            "canonical_technology_name",
            "technology_variant",
            "binder_component_1",
            "binder_component_2",
        ):
            if _nonempty(record.get(key)):
                terms.append(str(record.get(key)))
    elif "replacement" in field or "clinker" in field:
        for key in ("raw_technology_name", "canonical_technology_name", "technology_variant"):
            if _nonempty(record.get(key)):
                terms.append(str(record.get(key)))
        terms.extend(["cement", "replacement", "fly ash", "clinker"])
    elif "co2" in field or "carbon" in field:
        terms.extend(["co2", "carbon", "emission", "capture"])
    return terms


def align_record_evidence(
    record: dict[str, Any],
    *,
    source_text: str,
    content_source: str = "",
) -> EvidenceAlignmentResult:
    """
    Align ``evidence_text`` to supporting spans in ``source_text``.

    - Taxonomy-critical slugs: evidence must include mapped support terms.
    - Populated numeric fields: evidence (or a better span) must include the number
      (and unit when required); otherwise the optional field is cleared.
    - Does not invent wording; only selects existing source spans.
    """
    cleared: list[str] = []
    text = _normalize_for_match(source_text)
    current = str(record.get("evidence_text") or "").strip()
    slug = str(record.get("sub_subcategory_slug") or "").strip()
    method = "unchanged"
    reason = "existing evidence retained"
    taxonomy_supported = True

    # 1) Taxonomy-critical evidence
    required = taxonomy_support_terms(slug)
    if required:
        if current and span_has_taxonomy_support(current, slug):
            taxonomy_supported = True
            method = "existing_taxonomy_span"
            reason = "existing evidence_text already contains taxonomy support terms"
        else:
            better = find_best_taxonomy_span(text, slug, preferred=current)
            if better:
                record["evidence_text"] = better
                current = better
                taxonomy_supported = True
                method = "taxonomy_span_search"
                reason = f"selected span containing support terms for {slug}"
            else:
                taxonomy_supported = False
                method = "taxonomy_unsupported"
                reason = (
                    f"no span in source supports taxonomy {slug}; "
                    "generic CCS phrasing is insufficient"
                )
                # Do not keep a misleading high-confidence taxonomy label
                if str(record.get("taxonomy_confidence") or "") == "High":
                    record["taxonomy_confidence"] = "Low"
                notes = str(record.get("notes") or "")
                flag = f"taxonomy_evidence_unaligned:{slug}"
                if flag not in notes:
                    record["notes"] = f"{notes} | {flag}".strip(" |")

    # 2) Numeric / binder fields — clear unsupported optional values
    unit_by_value_field = {v: u for v, u in UNIT_FIELD_PAIRS}
    for field in NUMERIC_EVIDENCE_FIELDS:
        if not _nonempty(record.get(field)):
            continue
        value = str(record.get(field)).strip()
        unit = str(record.get(unit_by_value_field.get(field, ""), "") or "")
        ctx = _context_terms_for_field(record, field)
        if current and span_supports_numeric_value(
            current, value, unit=unit, context_terms=ctx
        ):
            continue
        better = find_best_numeric_span(
            text, value, unit=unit, context_terms=ctx, preferred=current
        )
        if better:
            # Prefer a span that also keeps taxonomy support when required
            if required and not span_has_taxonomy_support(better, slug):
                # Try to find a span that has BOTH number and taxonomy terms
                combined_candidates = split_candidate_spans(text, max_span_chars=900)
                both = ""
                for span in combined_candidates:
                    if span_has_taxonomy_support(span, slug) and span_supports_numeric_value(
                        span, value, unit=unit, context_terms=ctx
                    ):
                        both = span
                        break
                if both:
                    better = both
            record["evidence_text"] = better
            current = better
            method = "numeric_span_search"
            reason = f"expanded/replaced evidence to include numeric field {field}"
            continue
        # Unsupported optional field → clear
        record[field] = ""
        cleared.append(field)
        if field in unit_by_value_field:
            uf = unit_by_value_field[field]
            if _nonempty(record.get(uf)):
                record[uf] = ""
                cleared.append(uf)

    # If binder fractions were cleared, also drop orphan component names when both empty
    for idx in (1, 2, 3, 4):
        frac = f"binder_component_{idx}_fraction"
        name = f"binder_component_{idx}"
        if frac in cleared and not _nonempty(record.get(frac)):
            # keep name if present — name alone is ok; fraction was the claim
            pass

    # Rebuild binder_components_json if fractions were cleared
    if any(f.startswith("binder_component_") and f.endswith("_fraction") for f in cleared):
        components = []
        for idx in (1, 2, 3, 4):
            name = str(record.get(f"binder_component_{idx}") or "").strip()
            frac = str(record.get(f"binder_component_{idx}_fraction") or "").strip()
            if name and frac:
                try:
                    components.append(
                        {
                            "component_name": name,
                            "canonical_component_name": name,
                            "fraction_percent": float(frac),
                        }
                    )
                except ValueError:
                    components.append(
                        {
                            "component_name": name,
                            "canonical_component_name": name,
                            "fraction_percent": frac,
                        }
                    )
        import json

        record["binder_components_json"] = json.dumps(components) if components else ""

    if content_source:
        record.setdefault("evidence_page_or_section", "")
        # Soft provenance note only when empty
        if not str(record.get("evidence_page_or_section") or "").strip():
            record["evidence_page_or_section"] = f"content_source:{content_source}"

    final_evidence = str(record.get("evidence_text") or "").strip()
    if required and final_evidence and not span_has_taxonomy_support(final_evidence, slug):
        taxonomy_supported = False

    return EvidenceAlignmentResult(
        evidence_text=final_evidence,
        method=method,
        reason=reason,
        cleared_fields=cleared,
        taxonomy_supported=taxonomy_supported,
        source_window_used=final_evidence[:200],
    )
