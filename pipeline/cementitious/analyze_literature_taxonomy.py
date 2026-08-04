#!/usr/bin/env python3
"""
Optional taxonomy-support utility: vocabulary discovery and taxonomy validation
from a literature-mining material-composition CSV.

Does NOT replace or overwrite the approved Cementitious Materials taxonomy.
Does NOT classify solely from chemical composition.
Does NOT make live LLM calls unless --use-llm is supplied.

Usage:
  python -m pipeline.cementitious.analyze_literature_taxonomy \\
    --input "/path/to/Literature mining dataset.csv" \\
    --taxonomy config/cementitious_materials_taxonomy.yaml \\
    --output "${RESULTS_ROOT}/7-30 results/metadata/literature_taxonomy_analysis"
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.taxonomy import Taxonomy, TaxonomyNode, load_taxonomy

logger = logging.getLogger(__name__)

# ── Column aliases ───────────────────────────────────────────────────────────

MATERIAL_COLS = ("Material Name", "material_name", "Material", "material", "Name")
CAPTION_COLS = ("Caption", "caption")
DOI_COLS = ("DOI", "doi", "Doi")
DESCRIPTOR_COLS = ("Descriptor", "descriptor")
LLM_COLS = ("LLM Response", "LLM_Response", "llm_response", "LLM response")
CATEGORY_COLS = ("Category", "category", "Material Category")

OXIDE_HINTS = (
    "sio2",
    "al2o3",
    "fe2o3",
    "cao",
    "mgo",
    "so3",
    "na2o",
    "k2o",
    "tio2",
    "p2o5",
    "loi",
    "mno",
    "oxide",
)

# Abbreviations that must not be auto-merged without strong context
AMBIGUOUS_ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    "fa": ("fly ash", "coal ash", "fine aggregate", "fatty acid"),
    "ba": ("bottom ash", "biomass ash", "boric acid"),
    "rm": ("red mud", "raw meal", "raw material"),
    "gp": ("geopolymer", "gypsum plaster", "glass powder"),
    "mk": ("metakaolin", "mark", "mixture"),
    "sf": ("silica fume", "sand filler", "steel fiber"),
    "sa": ("silica ash", "sodium aluminate"),
    "ca": ("calcium", "coal ash", "citric acid"),
    "ls": ("limestone", "lime sludge"),
}

ARTIFACT_EXACT = frozenset(
    {
        "literature",
        "table",
        "caption",
        "figure",
        "fig",
        "note",
        "notes",
        "reference",
        "references",
        "citation",
        "citations",
        "author",
        "authors",
        "material",
        "materials",
        "sample",
        "samples",
        "mix",
        "mixture",
        "control",
        "blank",
        "n/a",
        "na",
        "none",
        "null",
        "-",
        "--",
        "total",
        "sum",
        "average",
        "mean",
        "composition",
        "chemical composition",
        "oxide composition",
    }
)

AUTHOR_LIKE = re.compile(
    r"^[A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+(?:and|&)\s+[A-Z][a-z]+)+(?:\s+et\s+al\.?)?$"
)
AUTHOR_ET_AL = re.compile(
    r"^[A-Z][a-z]+(?:\s+[A-Z]\.?)*(?:\s+et\s+al\.?)$"
)
CITATION_LIKE = re.compile(
    r"(?:doi\s*:|https?://|et\s+al\.|vol\.|pp\.|\(\d{4}\))",
    re.IGNORECASE,
)

# Table/sample mix IDs: S1, M3, V6a, 1027A, Mix-2, C-01, etc.
SAMPLE_ID_PATTERNS = (
    re.compile(r"^(?:mix|sample|specimen|batch|series)[\s_\-]*[a-z]?\d+[a-z]?$", re.I),
    re.compile(r"^[smvcfrpt]\d{1,3}[a-z]?$", re.I),
    re.compile(r"^\d{2,4}[a-z]$", re.I),
    re.compile(r"^[a-z]\d{1,3}$", re.I),
    re.compile(r"^(?:m|s|c|v|f|r)[\s_\-]*\d+[a-z]?$", re.I),
)

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_UNRESOLVED = "Unresolved"
CONFIDENCE_ARTIFACT = "Artifact"


@dataclass
class LexiconEntry:
    subcategory_slug: str
    subcategory: str
    sub_subcategory_slug: str
    sub_subcategory: str
    technology_variant: str
    term_type: str  # synonym | display | variant | cue


@dataclass
class NameAggregate:
    raw_name: str
    normalized_name: str
    frequency: int = 0
    dois: set[str] = field(default_factory=set)
    categories: Counter = field(default_factory=Counter)
    captions: list[str] = field(default_factory=list)
    descriptors: list[str] = field(default_factory=list)
    llm_snippets: list[str] = field(default_factory=list)
    oxide_rows: list[dict[str, str]] = field(default_factory=list)


@dataclass
class MappingResult:
    raw_material_name: str
    normalized_name: str
    frequency: int
    unique_doi_count: int
    existing_dataset_category: str
    proposed_subcategory: str
    proposed_subcategory_slug: str
    proposed_sub_subcategory: str
    proposed_sub_subcategory_slug: str
    proposed_technology_variant: str
    representative_captions: str
    representative_doi: str
    confidence: str
    mapping_rationale: str
    human_review_required: str
    status: str  # mapped | ambiguous | unresolved | artifact | sample_id
    oxide_validation: str = ""


def _pick_col(fieldnames: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    lower = {f.casefold(): f for f in fieldnames}
    for alias in aliases:
        if alias.casefold() in lower:
            return lower[alias.casefold()]
    return None


def _oxide_columns(fieldnames: Iterable[str]) -> list[str]:
    cols = []
    for name in fieldnames:
        key = re.sub(r"[^a-z0-9]", "", name.casefold())
        if any(h in key for h in OXIDE_HINTS):
            cols.append(name)
    return cols


def normalize_material_name(raw: str) -> str:
    """Normalize capitalization, punctuation, whitespace, and encoding artifacts."""
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("–", "-").replace("—", "-").replace("′", "'").replace("’", "'")
    text = text.strip().strip("\"'`")
    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text)
    # Normalize common separators around slashes/hyphens
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s*-\s*", "-", text)
    # Drop trailing parenthetical sample codes only when clearly IDs: (S1), (M3)
    text = re.sub(r"\s*\((?:[SMVCFRPT]?\d+[a-zA-Z]?|[Mm]ix\s*\d+)\)\s*$", "", text)
    text = text.strip(" ,;:")
    return text


def normalize_key(name: str) -> str:
    """Casefolded matching key."""
    text = normalize_material_name(name).casefold()
    text = text.replace("&", " and ")
    text = text.replace("-", " ").replace("/", " ")
    text = re.sub(r"[^\w\s.+]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_sample_or_mix_id(name: str) -> bool:
    n = normalize_material_name(name)
    if not n or len(n) > 24:
        return False
    # Reject if it looks like a known material phrase
    if any(
        tok in n.casefold()
        for tok in (
            "ash",
            "slag",
            "cement",
            "clay",
            "fume",
            "lime",
            "pozzolan",
            "kaolin",
            "silica",
            "fly",
            "geopolymer",
        )
    ):
        return False
    return any(p.match(n) for p in SAMPLE_ID_PATTERNS)


def is_extraction_artifact(name: str, *, caption: str = "", descriptor: str = "") -> bool:
    n = normalize_material_name(name)
    key = n.casefold()
    if not n:
        return True
    if key in ARTIFACT_EXACT:
        return True
    if key.startswith("table ") or key.startswith("fig ") or key.startswith("figure "):
        return True
    if CITATION_LIKE.search(n):
        return True
    if AUTHOR_LIKE.match(n) or AUTHOR_ET_AL.match(n):
        if "cement" not in key and "ash" not in key:
            return True
    # Single very short non-abbreviation tokens that are headings
    if key in {"sio2", "al2o3", "cao", "composition", "wt%", "wt. %"}:
        return True
    blob = f"{caption} {descriptor}".casefold()
    if key in {"literature"} or (key == "material" and "heading" in blob):
        return True
    return False


def _build_lexicon(taxonomy: Taxonomy) -> dict[str, list[LexiconEntry]]:
    lexicon: dict[str, list[LexiconEntry]] = defaultdict(list)

    def add(term: str, entry: LexiconEntry) -> None:
        key = normalize_key(term)
        if not key or len(key) < 2:
            return
        lexicon[key].append(entry)

    for ss_slug, node in taxonomy.sub_subcategories.items():
        parent_slug = taxonomy.parent_of_sub_sub[ss_slug]
        parent = taxonomy.subcategories[parent_slug]
        base = dict(
            subcategory_slug=parent_slug,
            subcategory=parent.display_name,
            sub_subcategory_slug=ss_slug,
            sub_subcategory=node.display_name,
        )
        add(node.display_name, LexiconEntry(**base, technology_variant="", term_type="display"))
        for syn in node.representative_synonyms:
            add(syn, LexiconEntry(**base, technology_variant="", term_type="synonym"))
        for var in node.representative_technology_variants:
            add(
                var,
                LexiconEntry(**base, technology_variant=var, term_type="variant"),
            )
        for cue in node.positive_screening_cues:
            if len(cue) >= 4:
                add(cue, LexiconEntry(**base, technology_variant="", term_type="cue"))
        for term in node.retrieval_query_terms:
            if len(term) >= 4:
                add(term, LexiconEntry(**base, technology_variant="", term_type="cue"))
    return lexicon


def _context_blob(agg: NameAggregate) -> str:
    parts = [
        agg.normalized_name,
        " ".join(agg.categories.keys()),
        " ".join(agg.captions[:5]),
        " ".join(agg.descriptors[:5]),
        " ".join(agg.llm_snippets[:3]),
    ]
    return " ".join(parts).casefold()


def _oxide_secondary_signal(agg: NameAggregate, proposed_ss: str) -> str:
    """Optional secondary validation; never primary classification."""
    if not agg.oxide_rows or not proposed_ss:
        return ""
    # Average numeric oxides when present
    totals: dict[str, list[float]] = defaultdict(list)
    for row in agg.oxide_rows[:20]:
        for k, v in row.items():
            try:
                totals[k.casefold()].append(float(str(v).replace("%", "").strip()))
            except ValueError:
                continue
    if not totals:
        return ""

    def mean(keys: tuple[str, ...]) -> float | None:
        vals = []
        for key in keys:
            vals.extend(totals.get(key, []))
        return sum(vals) / len(vals) if vals else None

    sio2 = mean(("sio2", "siO2".casefold()))
    cao = mean(("cao",))
    al2o3 = mean(("al2o3",))
    notes = []
    ss = proposed_ss
    if ss in {"silica_fume"} and sio2 is not None and sio2 < 70:
        notes.append("oxide_signal_conflict: silica_fume usually high SiO2")
    if ss in {"coal_ash", "biomass_ashes"} and cao is not None and cao > 50 and sio2 is not None and sio2 < 20:
        notes.append("oxide_signal_unusual: ash-like label but CaO-dominant")
    if ss in {"slag_cement"} and cao is not None and cao < 20 and sio2 is not None and sio2 > 60:
        notes.append("oxide_signal_conflict: slag usually CaO-rich")
    if ss in {"calcined_clays"} and al2o3 is not None and al2o3 < 10:
        notes.append("oxide_signal_unusual: calcined clay often Al2O3-bearing")
    if not notes and (sio2 is not None or cao is not None):
        return "oxide_secondary_ok"
    return "; ".join(notes)


def _best_lexicon_hit(
    key: str, lexicon: dict[str, list[LexiconEntry]]
) -> tuple[LexiconEntry | None, str]:
    if key in lexicon:
        entries = lexicon[key]
        # Prefer display/variant/synonym over cue
        rank = {"display": 0, "variant": 1, "synonym": 2, "cue": 3}
        entries = sorted(entries, key=lambda e: rank.get(e.term_type, 9))
        # If multiple distinct sub_subcategories, ambiguous
        ss = {e.sub_subcategory_slug for e in entries}
        if len(ss) > 1:
            return None, "ambiguous_lexicon_collision"
        return entries[0], "exact_lexicon"
    # Containment: longer lexicon terms contained in name or vice versa
    candidates: list[tuple[int, LexiconEntry]] = []
    for term, entries in lexicon.items():
        if len(term) < 4:
            continue
        if term in key or key in term:
            for e in entries:
                if e.term_type == "cue" and len(term) < 8:
                    continue
                candidates.append((len(term), e))
    if not candidates:
        return None, ""
    candidates.sort(key=lambda t: -t[0])
    top_len = candidates[0][0]
    top_entries = [e for n, e in candidates if n == top_len]
    if len({e.sub_subcategory_slug for e in top_entries}) > 1:
        return None, "ambiguous_partial_match"
    return top_entries[0], "partial_lexicon"


def _resolve_abbreviation(
    key: str, context: str, lexicon: dict[str, list[LexiconEntry]]
) -> tuple[LexiconEntry | None, str, bool]:
    """Return (entry, rationale, needs_review). Never auto-merge without context."""
    if key not in AMBIGUOUS_ABBREVIATIONS:
        return None, "", False
    senses = AMBIGUOUS_ABBREVIATIONS[key]
    matched_senses = []
    for sense in senses:
        if sense in context:
            matched_senses.append(sense)
    if len(matched_senses) == 1:
        hit, how = _best_lexicon_hit(normalize_key(matched_senses[0]), lexicon)
        if hit:
            return (
                hit,
                f"abbreviation_resolved_via_context:{key}->{matched_senses[0]}",
                True,
            )
    if not matched_senses:
        # Check lexicon expansion hints in context for known expansions
        for sense in senses:
            hit, _ = _best_lexicon_hit(normalize_key(sense), lexicon)
            if hit and (
                hit.sub_subcategory.casefold() in context
                or any(s in context for s in hit.sub_subcategory.casefold().split() if len(s) > 4)
            ):
                return hit, f"abbreviation_weak_context:{key}", True
    return None, f"ambiguous_abbreviation:{key}", True


def map_material_name(
    agg: NameAggregate,
    *,
    lexicon: dict[str, list[LexiconEntry]],
    taxonomy: Taxonomy,
) -> MappingResult:
    raw = agg.raw_name
    norm = agg.normalized_name
    key = normalize_key(norm)
    top_category = agg.categories.most_common(1)[0][0] if agg.categories else ""
    captions = " | ".join(agg.captions[:3])
    doi = next(iter(sorted(agg.dois)), "")
    freq = agg.frequency
    doi_n = len(agg.dois)

    def result(**kwargs: Any) -> MappingResult:
        defaults = dict(
            raw_material_name=raw,
            normalized_name=norm,
            frequency=freq,
            unique_doi_count=doi_n,
            existing_dataset_category=top_category,
            proposed_subcategory="",
            proposed_subcategory_slug="",
            proposed_sub_subcategory="",
            proposed_sub_subcategory_slug="",
            proposed_technology_variant="",
            representative_captions=captions,
            representative_doi=doi,
            confidence=CONFIDENCE_UNRESOLVED,
            mapping_rationale="",
            human_review_required="yes",
            status="unresolved",
            oxide_validation="",
        )
        defaults.update(kwargs)
        return MappingResult(**defaults)

    if is_extraction_artifact(raw) or is_extraction_artifact(norm):
        return result(
            confidence=CONFIDENCE_ARTIFACT,
            mapping_rationale="extraction_artifact_or_heading",
            human_review_required="yes",
            status="artifact",
        )
    if is_sample_or_mix_id(raw) or is_sample_or_mix_id(norm):
        return result(
            confidence=CONFIDENCE_ARTIFACT,
            mapping_rationale="sample_or_mix_id_label",
            human_review_required="yes",
            status="sample_id",
        )

    context = _context_blob(agg)

    # Ambiguous abbreviations first
    if key in AMBIGUOUS_ABBREVIATIONS or (
        len(key) <= 3 and key.isalpha() and key in AMBIGUOUS_ABBREVIATIONS
    ):
        entry, rationale, review = _resolve_abbreviation(key, context, lexicon)
        if entry is None:
            return result(
                confidence=CONFIDENCE_LOW,
                mapping_rationale=rationale or "ambiguous_abbreviation_unresolved",
                human_review_required="yes",
                status="ambiguous",
            )
        oxide = _oxide_secondary_signal(agg, entry.sub_subcategory_slug)
        return result(
            proposed_subcategory=entry.subcategory,
            proposed_subcategory_slug=entry.subcategory_slug,
            proposed_sub_subcategory=entry.sub_subcategory,
            proposed_sub_subcategory_slug=entry.sub_subcategory_slug,
            proposed_technology_variant=entry.technology_variant or entry.sub_subcategory,
            confidence=CONFIDENCE_MEDIUM,
            mapping_rationale=rationale,
            human_review_required="yes" if review else "no",
            status="ambiguous" if review else "mapped",
            oxide_validation=oxide,
        )

    hit, how = _best_lexicon_hit(key, lexicon)
    if hit and how.startswith("ambiguous"):
        return result(
            confidence=CONFIDENCE_LOW,
            mapping_rationale=how,
            human_review_required="yes",
            status="ambiguous",
        )
    if hit:
        conf = CONFIDENCE_HIGH if how == "exact_lexicon" else CONFIDENCE_MEDIUM
        oxide = _oxide_secondary_signal(agg, hit.sub_subcategory_slug)
        if oxide.startswith("oxide_signal_conflict"):
            conf = CONFIDENCE_LOW
            review = "yes"
            status = "ambiguous"
        else:
            review = "no" if conf == CONFIDENCE_HIGH else "yes"
            status = "mapped"
        variant = hit.technology_variant
        if not variant and how == "exact_lexicon" and hit.term_type == "variant":
            variant = hit.technology_variant
        if not variant:
            # If normalized name matches a known variant spelling, keep it
            for v in taxonomy.sub_subcategories[hit.sub_subcategory_slug].representative_technology_variants:
                if normalize_key(v) == key:
                    variant = v
                    break
        return result(
            proposed_subcategory=hit.subcategory,
            proposed_subcategory_slug=hit.subcategory_slug,
            proposed_sub_subcategory=hit.sub_subcategory,
            proposed_sub_subcategory_slug=hit.sub_subcategory_slug,
            proposed_technology_variant=variant,
            confidence=conf,
            mapping_rationale=f"{how}:{hit.term_type}",
            human_review_required=review,
            status=status,
            oxide_validation=oxide,
        )

    # Context-only soft mapping: look for sub_subcategory display names in context
    soft_hits: list[TaxonomyNode] = []
    for ss_slug, node in taxonomy.sub_subcategories.items():
        dn = node.display_name.casefold()
        if len(dn) >= 5 and dn in context:
            soft_hits.append(node)
        else:
            for syn in node.representative_synonyms:
                if len(syn) >= 5 and syn.casefold() in context:
                    soft_hits.append(node)
                    break
    soft_hits = list({n.slug: n for n in soft_hits}.values())
    if len(soft_hits) == 1:
        node = soft_hits[0]
        parent_slug = taxonomy.parent_of_sub_sub[node.slug]
        parent = taxonomy.subcategories[parent_slug]
        oxide = _oxide_secondary_signal(agg, node.slug)
        return result(
            proposed_subcategory=parent.display_name,
            proposed_subcategory_slug=parent_slug,
            proposed_sub_subcategory=node.display_name,
            proposed_sub_subcategory_slug=node.slug,
            proposed_technology_variant="",
            confidence=CONFIDENCE_LOW,
            mapping_rationale="context_only_soft_match",
            human_review_required="yes",
            status="ambiguous",
            oxide_validation=oxide,
        )
    if len(soft_hits) > 1:
        return result(
            confidence=CONFIDENCE_LOW,
            mapping_rationale="context_multiple_candidates:"
            + ",".join(n.slug for n in soft_hits[:5]),
            human_review_required="yes",
            status="ambiguous",
        )

    return result(
        confidence=CONFIDENCE_UNRESOLVED,
        mapping_rationale="no_taxonomy_match",
        human_review_required="yes",
        status="unresolved",
    )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _mapping_row(m: MappingResult) -> dict[str, Any]:
    return {
        "raw_material_name": m.raw_material_name,
        "normalized_name": m.normalized_name,
        "frequency": m.frequency,
        "unique_doi_count": m.unique_doi_count,
        "existing_dataset_category": m.existing_dataset_category,
        "proposed_subcategory": m.proposed_subcategory,
        "proposed_subcategory_slug": m.proposed_subcategory_slug,
        "proposed_sub_subcategory": m.proposed_sub_subcategory,
        "proposed_sub_subcategory_slug": m.proposed_sub_subcategory_slug,
        "proposed_technology_variant": m.proposed_technology_variant,
        "representative_captions": m.representative_captions,
        "representative_doi": m.representative_doi,
        "confidence": m.confidence,
        "mapping_rationale": m.mapping_rationale,
        "human_review_required": m.human_review_required,
        "status": m.status,
        "oxide_validation": m.oxide_validation,
    }


MAPPING_FIELDS = [
    "raw_material_name",
    "normalized_name",
    "frequency",
    "unique_doi_count",
    "existing_dataset_category",
    "proposed_subcategory",
    "proposed_subcategory_slug",
    "proposed_sub_subcategory",
    "proposed_sub_subcategory_slug",
    "proposed_technology_variant",
    "representative_captions",
    "representative_doi",
    "confidence",
    "mapping_rationale",
    "human_review_required",
    "status",
    "oxide_validation",
]


def load_literature_rows(input_path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {input_path}")
        fields = list(reader.fieldnames)
        colmap = {
            "material": _pick_col(fields, MATERIAL_COLS),
            "caption": _pick_col(fields, CAPTION_COLS),
            "doi": _pick_col(fields, DOI_COLS),
            "descriptor": _pick_col(fields, DESCRIPTOR_COLS),
            "llm": _pick_col(fields, LLM_COLS),
            "category": _pick_col(fields, CATEGORY_COLS),
        }
        if not colmap["material"]:
            raise ValueError(
                "Could not find a Material Name column. "
                f"Looked for {MATERIAL_COLS}; found {fields}"
            )
        oxide_cols = _oxide_columns(fields)
        rows = []
        for raw in reader:
            rows.append({k: (v or "").strip() if isinstance(v, str) else str(v or "") for k, v in raw.items()})
        colmap["oxides"] = ",".join(oxide_cols)
        return rows, {k: v or "" for k, v in colmap.items()}


def aggregate_names(
    rows: list[dict[str, str]], colmap: dict[str, str]
) -> dict[str, NameAggregate]:
    material_col = colmap["material"]
    oxide_cols = [c for c in colmap.get("oxides", "").split(",") if c]
    by_norm: dict[str, NameAggregate] = {}

    for row in rows:
        raw = row.get(material_col, "")
        if not raw.strip():
            continue
        norm = normalize_material_name(raw)
        key = normalize_key(norm)
        if key not in by_norm:
            by_norm[key] = NameAggregate(raw_name=raw.strip(), normalized_name=norm)
        agg = by_norm[key]
        # Prefer longer / title-cased raw form
        if len(raw.strip()) > len(agg.raw_name):
            agg.raw_name = raw.strip()
        agg.frequency += 1
        doi = row.get(colmap.get("doi") or "", "").strip()
        if doi:
            agg.dois.add(doi)
        cat = row.get(colmap.get("category") or "", "").strip()
        if cat:
            agg.categories[cat] += 1
        for src_key, attr in (
            ("caption", "captions"),
            ("descriptor", "descriptors"),
            ("llm", "llm_snippets"),
        ):
            col = colmap.get(src_key) or ""
            val = row.get(col, "").strip() if col else ""
            if val:
                bucket: list[str] = getattr(agg, attr)
                if len(bucket) < 8 and val not in bucket:
                    bucket.append(val[:500])
        if oxide_cols:
            oxide = {c: row.get(c, "") for c in oxide_cols if row.get(c, "")}
            if oxide and len(agg.oxide_rows) < 30:
                agg.oxide_rows.append(oxide)
    return by_norm


def analyze(
    *,
    input_path: Path,
    taxonomy: Taxonomy,
    output_dir: Path,
    write_synonym_file: bool = True,
    synonym_output: Path | None = None,
    use_llm: bool = False,
) -> dict[str, Any]:
    if use_llm:
        logger.warning(
            "--use-llm supplied: LLM enrichment is optional and currently unused "
            "in the deterministic analyzer (no live calls performed)."
        )

    rows, colmap = load_literature_rows(input_path)
    aggregates = aggregate_names(rows, colmap)
    lexicon = _build_lexicon(taxonomy)

    mappings: list[MappingResult] = []
    for agg in sorted(aggregates.values(), key=lambda a: (-a.frequency, a.normalized_name.casefold())):
        mappings.append(map_material_name(agg, lexicon=lexicon, taxonomy=taxonomy))

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) observed_material_names.csv
    observed_rows = []
    for m in mappings:
        agg = aggregates[normalize_key(m.normalized_name)]
        observed_rows.append(
            {
                **_mapping_row(m),
                "raw_material_name": agg.raw_name,
                "normalized_name": agg.normalized_name,
                "dataset_category_top": agg.categories.most_common(1)[0][0] if agg.categories else "",
                "dataset_category_all": " | ".join(
                    f"{k}:{v}" for k, v in agg.categories.most_common(5)
                ),
            }
        )
    _write_csv(
        output_dir / "observed_material_names.csv",
        MAPPING_FIELDS
        + ["dataset_category_top", "dataset_category_all"],
        observed_rows,
    )

    # 2) proposed_synonym_mappings.csv — confident/medium mapped non-artifacts
    synonym_rows = [
        _mapping_row(m)
        for m in mappings
        if m.status == "mapped"
        and m.confidence in {CONFIDENCE_HIGH, CONFIDENCE_MEDIUM}
        and m.proposed_sub_subcategory_slug
    ]
    _write_csv(output_dir / "proposed_synonym_mappings.csv", MAPPING_FIELDS, synonym_rows)

    # 3) unresolved
    unresolved = [_mapping_row(m) for m in mappings if m.status == "unresolved"]
    _write_csv(output_dir / "unresolved_material_names.csv", MAPPING_FIELDS, unresolved)

    # 4) ambiguous abbreviations
    ambig = [
        _mapping_row(m)
        for m in mappings
        if m.status == "ambiguous"
        or "abbreviation" in m.mapping_rationale
        or normalize_key(m.normalized_name) in AMBIGUOUS_ABBREVIATIONS
    ]
    _write_csv(output_dir / "ambiguous_abbreviations.csv", MAPPING_FIELDS, ambig)

    # 5) category_crosswalk.csv
    cross: dict[tuple[str, str, str], dict[str, Any]] = {}
    for m in mappings:
        key = (
            m.existing_dataset_category or "(blank)",
            m.proposed_subcategory_slug or "(unmapped)",
            m.proposed_sub_subcategory_slug or "(unmapped)",
        )
        if key not in cross:
            cross[key] = {
                "existing_dataset_category": key[0],
                "proposed_subcategory_slug": key[1],
                "proposed_sub_subcategory_slug": key[2],
                "proposed_subcategory": m.proposed_subcategory,
                "proposed_sub_subcategory": m.proposed_sub_subcategory,
                "material_name_count": 0,
                "row_frequency": 0,
                "example_names": [],
            }
        cross[key]["material_name_count"] += 1
        cross[key]["row_frequency"] += m.frequency
        if len(cross[key]["example_names"]) < 5:
            cross[key]["example_names"].append(m.normalized_name)
    cross_rows = []
    for row in sorted(cross.values(), key=lambda r: -r["row_frequency"]):
        row = dict(row)
        row["example_names"] = " | ".join(row["example_names"])
        cross_rows.append(row)
    _write_csv(
        output_dir / "category_crosswalk.csv",
        [
            "existing_dataset_category",
            "proposed_subcategory",
            "proposed_subcategory_slug",
            "proposed_sub_subcategory",
            "proposed_sub_subcategory_slug",
            "material_name_count",
            "row_frequency",
            "example_names",
        ],
        cross_rows,
    )

    # 6) proposed_technology_variants.csv — only variants, not new nodes
    known_variants: set[tuple[str, str]] = set()
    for ss_slug, node in taxonomy.sub_subcategories.items():
        for v in node.representative_technology_variants:
            known_variants.add((ss_slug, normalize_key(v)))
        known_variants.add((ss_slug, normalize_key(node.display_name)))

    variant_rows = []
    for m in mappings:
        if m.status not in {"mapped", "ambiguous"}:
            continue
        if not m.proposed_sub_subcategory_slug:
            continue
        nk = normalize_key(m.normalized_name)
        if (m.proposed_sub_subcategory_slug, nk) in known_variants:
            continue
        # Skip pure abbreviations and artifacts
        if m.status == "sample_id" or m.confidence == CONFIDENCE_ARTIFACT:
            continue
        if len(nk) <= 3:
            continue
        variant_rows.append(
            {
                **_mapping_row(m),
                "suggestion_type": "technology_variant_only",
                "note": "Pending human approval; not written into approved taxonomy",
            }
        )
    _write_csv(
        output_dir / "proposed_technology_variants.csv",
        MAPPING_FIELDS + ["suggestion_type", "note"],
        variant_rows,
    )

    # 7) taxonomy_coverage_summary.csv
    total_names = len(mappings) or 1
    total_rows = sum(m.frequency for m in mappings) or 1
    counts = Counter(m.status for m in mappings)
    conf_counts = Counter(m.confidence for m in mappings)
    mapped_conf = sum(1 for m in mappings if m.status == "mapped" and m.confidence == CONFIDENCE_HIGH)
    mapped_amb = sum(
        1
        for m in mappings
        if m.status in {"ambiguous", "mapped"} and m.confidence in {CONFIDENCE_MEDIUM, CONFIDENCE_LOW}
    )
    unresolved_n = counts.get("unresolved", 0)
    artifact_n = counts.get("artifact", 0) + counts.get("sample_id", 0)
    coverage_rows = [
        {
            "metric": "total_csv_rows",
            "value": len(rows),
            "percent": "",
        },
        {
            "metric": "unique_material_names",
            "value": len(mappings),
            "percent": "",
        },
        {
            "metric": "unique_dois",
            "value": len({d for a in aggregates.values() for d in a.dois}),
            "percent": "",
        },
        {
            "metric": "percent_confidently_mapped",
            "value": mapped_conf,
            "percent": f"{100.0 * mapped_conf / total_names:.2f}",
        },
        {
            "metric": "percent_ambiguously_mapped",
            "value": mapped_amb,
            "percent": f"{100.0 * mapped_amb / total_names:.2f}",
        },
        {
            "metric": "percent_unresolved",
            "value": unresolved_n,
            "percent": f"{100.0 * unresolved_n / total_names:.2f}",
        },
        {
            "metric": "percent_probable_extraction_artifacts",
            "value": artifact_n,
            "percent": f"{100.0 * artifact_n / total_names:.2f}",
        },
        {
            "metric": "row_weighted_confident_mapped_percent",
            "value": sum(
                m.frequency
                for m in mappings
                if m.status == "mapped" and m.confidence == CONFIDENCE_HIGH
            ),
            "percent": f"{100.0 * sum(m.frequency for m in mappings if m.status == 'mapped' and m.confidence == CONFIDENCE_HIGH) / total_rows:.2f}",
        },
    ]
    for status, n in sorted(counts.items()):
        coverage_rows.append(
            {"metric": f"status_{status}", "value": n, "percent": f"{100.0 * n / total_names:.2f}"}
        )
    for conf, n in sorted(conf_counts.items()):
        coverage_rows.append(
            {"metric": f"confidence_{conf}", "value": n, "percent": f"{100.0 * n / total_names:.2f}"}
        )
    _write_csv(
        output_dir / "taxonomy_coverage_summary.csv",
        ["metric", "value", "percent"],
        coverage_rows,
    )

    # 8) material_frequency_by_source.csv
    freq_by_source = []
    for agg in aggregates.values():
        m = next(x for x in mappings if normalize_key(x.normalized_name) == normalize_key(agg.normalized_name))
        if not agg.dois:
            freq_by_source.append(
                {
                    "doi": "",
                    "raw_material_name": agg.raw_name,
                    "normalized_name": agg.normalized_name,
                    "frequency_in_source": agg.frequency,
                    "existing_dataset_category": m.existing_dataset_category,
                    "proposed_sub_subcategory_slug": m.proposed_sub_subcategory_slug,
                    "status": m.status,
                }
            )
        else:
            # Approximate per-DOI: we don't store per-doi counts precisely in aggregate;
            # emit one row per DOI with shared frequency note.
            per = max(1, agg.frequency // max(1, len(agg.dois)))
            for doi in sorted(agg.dois):
                freq_by_source.append(
                    {
                        "doi": doi,
                        "raw_material_name": agg.raw_name,
                        "normalized_name": agg.normalized_name,
                        "frequency_in_source": per,
                        "existing_dataset_category": m.existing_dataset_category,
                        "proposed_sub_subcategory_slug": m.proposed_sub_subcategory_slug,
                        "status": m.status,
                    }
                )
    _write_csv(
        output_dir / "material_frequency_by_source.csv",
        [
            "doi",
            "raw_material_name",
            "normalized_name",
            "frequency_in_source",
            "existing_dataset_category",
            "proposed_sub_subcategory_slug",
            "status",
        ],
        freq_by_source,
    )

    # 9) data_quality_issues.csv
    issues = []
    for m in mappings:
        if m.status in {"artifact", "sample_id"}:
            issues.append(
                {
                    "issue_type": m.status,
                    "raw_material_name": m.raw_material_name,
                    "normalized_name": m.normalized_name,
                    "frequency": m.frequency,
                    "detail": m.mapping_rationale,
                    "severity": "medium",
                }
            )
        if "abbreviation" in m.mapping_rationale and m.human_review_required == "yes":
            issues.append(
                {
                    "issue_type": "ambiguous_abbreviation",
                    "raw_material_name": m.raw_material_name,
                    "normalized_name": m.normalized_name,
                    "frequency": m.frequency,
                    "detail": m.mapping_rationale,
                    "severity": "high",
                }
            )
        if m.oxide_validation.startswith("oxide_signal_conflict"):
            issues.append(
                {
                    "issue_type": "oxide_conflict",
                    "raw_material_name": m.raw_material_name,
                    "normalized_name": m.normalized_name,
                    "frequency": m.frequency,
                    "detail": m.oxide_validation,
                    "severity": "medium",
                }
            )
    # Blank materials
    blank = sum(1 for r in rows if not (r.get(colmap["material"]) or "").strip())
    if blank:
        issues.append(
            {
                "issue_type": "blank_material_name",
                "raw_material_name": "",
                "normalized_name": "",
                "frequency": blank,
                "detail": "rows with empty Material Name",
                "severity": "high",
            }
        )
    _write_csv(
        output_dir / "data_quality_issues.csv",
        [
            "issue_type",
            "raw_material_name",
            "normalized_name",
            "frequency",
            "detail",
            "severity",
        ],
        issues,
    )

    # Frequent unresolved concepts that may justify a new taxonomy node (review only)
    node_review = []
    for m in mappings:
        if m.status != "unresolved":
            continue
        if m.frequency < 3:
            continue
        if len(normalize_key(m.normalized_name)) < 5:
            continue
        node_review.append(
            {
                **_mapping_row(m),
                "suggestion_type": "possible_new_taxonomy_node_review_only",
                "note": "Do not auto-add subcategory/sub-subcategory; human review required",
            }
        )
    _write_csv(
        output_dir / "possible_new_taxonomy_nodes_for_review.csv",
        MAPPING_FIELDS + ["suggestion_type", "note"],
        node_review,
    )

    # Profile summary JSON
    category_freq = Counter()
    for row in rows:
        cat = row.get(colmap.get("category") or "", "").strip() or "(blank)"
        category_freq[cat] += 1
    profile = {
        "input_path": str(input_path),
        "taxonomy_path": taxonomy.source_path,
        "taxonomy_version": taxonomy.taxonomy_version,
        "total_rows": len(rows),
        "unique_material_names": len(mappings),
        "unique_dois": len({d for a in aggregates.values() for d in a.dois}),
        "category_frequencies": dict(category_freq.most_common()),
        "top_material_names": [
            {"name": m.normalized_name, "frequency": m.frequency, "status": m.status}
            for m in sorted(mappings, key=lambda x: -x.frequency)[:50]
        ],
        "coverage": {
            "percent_confidently_mapped": round(100.0 * mapped_conf / total_names, 2),
            "percent_ambiguously_mapped": round(100.0 * mapped_amb / total_names, 2),
            "percent_unresolved": round(100.0 * unresolved_n / total_names, 2),
            "percent_probable_extraction_artifacts": round(100.0 * artifact_n / total_names, 2),
        },
        "column_map": colmap,
        "use_llm": use_llm,
        "taxonomy_overwritten": False,
    }
    (output_dir / "analysis_profile.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8"
    )

    # Optional retrieval synonym file (pending approval)
    if write_synonym_file:
        syn_path = synonym_output or (REPO_ROOT / "config" / "generated_literature_synonyms.yaml")
        _write_pending_synonym_yaml(syn_path, synonym_rows, taxonomy)
        profile["generated_synonym_file"] = str(syn_path)

    (output_dir / "analysis_profile.json").write_text(
        json.dumps(profile, indent=2), encoding="utf-8"
    )
    return profile


def _write_pending_synonym_yaml(
    path: Path, synonym_rows: list[dict[str, Any]], taxonomy: Taxonomy
) -> None:
    """Write pending synonyms; never merge into approved taxonomy."""
    path.parent.mkdir(parents=True, exist_ok=True)
    by_ss: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in synonym_rows:
        slug = row.get("proposed_sub_subcategory_slug") or ""
        if not slug:
            continue
        by_ss[slug].append(row)

    lines = [
        "# GENERATED FILE — PENDING HUMAN APPROVAL",
        "# Do not treat as part of the approved Cementitious Materials taxonomy.",
        "# Source: pipeline.cementitious.analyze_literature_taxonomy",
        f"# taxonomy_version_referenced: {taxonomy.taxonomy_version}",
        "status: pending_approval",
        "overwrite_approved_taxonomy: false",
        "synonyms_by_sub_subcategory:",
    ]
    for slug in sorted(by_ss.keys()):
        node = taxonomy.sub_subcategories.get(slug)
        lines.append(f"  {slug}:")
        lines.append(f"    display_name: {json.dumps(node.display_name if node else slug)}")
        lines.append("    pending_synonyms:")
        seen = set()
        for row in sorted(by_ss[slug], key=lambda r: -int(r.get("frequency") or 0)):
            name = str(row.get("normalized_name") or "")
            key = normalize_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            # Skip if already an official synonym
            if node and key in {normalize_key(s) for s in node.representative_synonyms}:
                continue
            if node and key == normalize_key(node.display_name):
                continue
            lines.append(f"      - raw: {json.dumps(row.get('raw_material_name') or '')}")
            lines.append(f"        normalized: {json.dumps(name)}")
            lines.append(f"        frequency: {row.get('frequency')}")
            lines.append(f"        confidence: {json.dumps(row.get('confidence') or '')}")
            lines.append(f"        rationale: {json.dumps(row.get('mapping_rationale') or '')}")
            lines.append("        approved: false")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.cementitious.analyze_literature_taxonomy",
        description=(
            "Profile a literature-mining CSV and propose taxonomy synonym / "
            "variant mappings without modifying the approved taxonomy."
        ),
    )
    parser.add_argument("--input", required=True, help="Path to literature mining CSV")
    parser.add_argument(
        "--taxonomy",
        default="",
        help="Taxonomy YAML/JSON path (default: config cementitious taxonomy)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output directory for analysis CSVs",
    )
    parser.add_argument(
        "--synonym-output",
        default="",
        help="Optional path for generated_literature_synonyms.yaml "
        "(default: config/generated_literature_synonyms.yaml)",
    )
    parser.add_argument(
        "--no-synonym-file",
        action="store_true",
        help="Do not write config/generated_literature_synonyms.yaml",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Opt-in flag for future LLM enrichment (no live calls by default)",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input CSV not found: {input_path}")
    taxonomy = load_taxonomy(args.taxonomy or None)
    output_dir = Path(args.output).expanduser().resolve()
    synonym_output = (
        Path(args.synonym_output).expanduser().resolve() if args.synonym_output else None
    )

    profile = analyze(
        input_path=input_path,
        taxonomy=taxonomy,
        output_dir=output_dir,
        write_synonym_file=not args.no_synonym_file,
        synonym_output=synonym_output,
        use_llm=bool(args.use_llm),
    )
    print(json.dumps(profile, indent=2))
    print(f"Wrote analysis to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
