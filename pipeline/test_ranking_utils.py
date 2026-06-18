"""Lightweight checks for tiered relevance scoring and year normalization."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.relevance_scoring import passes_relevance_filter, score_relevance
from pipeline.year_utils import infer_year_from_doi, normalize_publication_year


def test_generic_concrete_filtered_out() -> None:
    text = (
        "This study examines compressive strength and durability of Portland cement concrete "
        "with fly ash aggregate under cyclic loading and corrosion exposure."
    )
    result = score_relevance(text)
    assert result.relevance_label == "Low"
    assert not passes_relevance_filter(result)


def test_decarbonization_ranks_high() -> None:
    text = (
        "Low-carbon concrete using calcined clay and supplementary cementitious materials "
        "achieved 35% CO2 reduction in embodied carbon."
    )
    result = score_relevance(text)
    assert result.relevance_label == "High"
    assert "decarbonization" in result.matched_tier1_keywords or "low-carbon" in result.matched_tier1_keywords
    assert passes_relevance_filter(result)


def test_negative_topics_penalized_without_decarbonization() -> None:
    text = "Radiation shielding performance of concrete with cement binder for nuclear facilities."
    result = score_relevance(text)
    assert result.negative_topic_matches
    assert result.relevance_label == "Low"


def test_year_metadata_preferred() -> None:
    year, source = normalize_publication_year({"year": 2015, "modified": 1640000000})
    assert year == "2015"
    assert source == "metadata"


def test_year_not_from_modified() -> None:
    year, source = normalize_publication_year({"modified": 1640000000})
    assert year == "Not Reported"
    assert source == "not_reported"


def test_year_doi_inferred() -> None:
    assert infer_year_from_doi("10.1016/j.cemconres.2018.05.012") == 2018
    year, source = normalize_publication_year({"doi": "10.1016/j.cemconres.2018.05.012"})
    assert year == "2018"
    assert source == "doi_inferred"


def main() -> int:
    tests = [
        test_generic_concrete_filtered_out,
        test_decarbonization_ranks_high,
        test_negative_topics_penalized_without_decarbonization,
        test_year_metadata_preferred,
        test_year_not_from_modified,
        test_year_doi_inferred,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
