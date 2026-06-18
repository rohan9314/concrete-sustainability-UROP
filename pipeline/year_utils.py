"""Publication year normalization for corpus records."""

from __future__ import annotations

import re

from pipeline.schema import NOT_REPORTED

_DOI_YEAR_PATTERNS = (
    re.compile(r"\.(19|20)\d{2}\."),
    re.compile(r"/(19|20)\d{2}/"),
    re.compile(r"\.(19|20)\d{2}/"),
)


def _coerce_year(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        year = value
    else:
        text = str(value).strip()
        match = re.search(r"(19|20)\d{2}", text)
        if not match:
            return None
        year = int(match.group(0))
    if 1900 <= year <= 2100:
        return year
    return None


def infer_year_from_doi(doi: str) -> int | None:
    """Cautiously infer publication year from a DOI when clearly present."""
    if not doi:
        return None
    doi_lower = doi.lower().strip()
    for pattern in _DOI_YEAR_PATTERNS:
        match = pattern.search(doi_lower)
        if match:
            year_text = re.search(r"(19|20)\d{2}", match.group(0))
            if year_text:
                year = int(year_text.group(0))
                if 1900 <= year <= 2100:
                    return year
    return None


def normalize_publication_year(record: dict) -> tuple[str, str]:
    """
    Return (year, year_source).

    year_source is one of: metadata, doi_inferred, not_reported
    """
    for key in ("year", "publication_year", "pub_year"):
        year = _coerce_year(record.get(key))
        if year is not None:
            return str(year), "metadata"

    doi = str(record.get("doi") or "").strip()
    inferred = infer_year_from_doi(doi)
    if inferred is not None:
        return str(inferred), "doi_inferred"

    return NOT_REPORTED, "not_reported"
