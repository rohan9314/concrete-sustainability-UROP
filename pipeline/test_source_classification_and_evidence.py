"""Unit tests for deterministic source classification and evidence alignment."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.evidence_alignment import (
    align_record_evidence,
    find_best_numeric_span,
    find_best_taxonomy_span,
    span_has_taxonomy_support,
    span_supports_numeric_value,
)
from pipeline.cementitious.source_classification import (
    SOURCE_TYPE_ACADEMIC_INSTITUTION,
    SOURCE_TYPE_ACADEMIC_LITERATURE,
    SOURCE_TYPE_COMPANY,
    SOURCE_TYPE_GOVERNMENT,
    SOURCE_TYPE_INDUSTRY_ASSOCIATION,
    SOURCE_TYPE_OTHER,
    SOURCE_TYPE_TECHNICAL_REPORT,
    classify_source_type,
    guess_source_type,
)
from pipeline.cementitious.schema import citation_from_record, WEB_SOURCE_TYPES
from pipeline.cementitious.web_tavily import guess_source_type as tavily_guess


def test_mdpi_is_academic_not_company() -> None:
    result = classify_source_type(
        url="https://www.mdpi.com/1996-1073/13/21/5692",
        title="CO2 Capture, Use, and Storage in the Cement Industry",
        domain="mdpi.com",
    )
    assert result.source_type == SOURCE_TYPE_ACADEMIC_LITERATURE
    assert result.source_type != SOURCE_TYPE_COMPANY
    assert result.method == "domain_rule"
    assert "mdpi.com" in result.matched_rule


def test_zkg_is_trade_publication_mapped_not_company() -> None:
    result = classify_source_type(
        url="https://www.zkg.de/en/artikel/next-generation-carbon-capture-technologies-for-cement-industries-3855861.html",
        title="Next-generation carbon capture technologies for cement industries",
        domain="zkg.de",
    )
    assert result.source_type == SOURCE_TYPE_TECHNICAL_REPORT
    assert result.source_type != SOURCE_TYPE_COMPANY
    assert "trade" in result.reason.casefold() or "zkg.de" in result.matched_rule


def test_wikipedia_is_not_company() -> None:
    result = classify_source_type(
        url="https://en.wikipedia.org/wiki/Cement",
        title="Cement",
        domain="en.wikipedia.org",
    )
    assert result.source_type == SOURCE_TYPE_OTHER
    assert result.source_type != SOURCE_TYPE_COMPANY


def test_energy_gov_is_government() -> None:
    result = classify_source_type(
        url="https://www.energy.gov/sites/default/files/guide.pdf",
        title="Industry Guide to CCS",
        domain="energy.gov",
    )
    assert result.source_type == SOURCE_TYPE_GOVERNMENT


def test_ieaghg_is_technical_report() -> None:
    result = classify_source_type(
        url="https://ieaghg.org/publications/2008-03%20CO2%20Capture%20in%20the%20Cement%20Industry.pdf",
        title="CO2 CAPTURE IN THE CEMENT INDUSTRY",
        domain="ieaghg.org",
    )
    assert result.source_type == SOURCE_TYPE_TECHNICAL_REPORT


def test_cement_org_is_industry_association() -> None:
    result = classify_source_type(
        url="https://www.cement.org/",
        title="American Cement Association",
        domain="cement.org",
    )
    assert result.source_type == SOURCE_TYPE_INDUSTRY_ASSOCIATION


def test_corporate_cement_company_is_company_website() -> None:
    result = classify_source_type(
        url="https://www.holcim.com/sustainability/carbon-capture",
        title="Holcim carbon capture solutions",
        domain="holcim.com",
    )
    assert result.source_type == SOURCE_TYPE_COMPANY


def test_unknown_domain_safe_fallback() -> None:
    result = classify_source_type(url="", title="", domain="")
    assert result.source_type in WEB_SOURCE_TYPES
    assert result.method in {"unknown", "domain_rule"}


def test_academic_publisher_beats_company_heuristic() -> None:
    # mdpi.com is a commercial publisher host but must not be Company Website.
    assert guess_source_type("https://mdpi.com/article/1", domain="mdpi.com") == (
        SOURCE_TYPE_ACADEMIC_LITERATURE
    )
    assert tavily_guess("https://mdpi.com/article/1", domain="mdpi.com") == (
        SOURCE_TYPE_ACADEMIC_LITERATURE
    )


def test_government_pdf_inherits_government() -> None:
    result = classify_source_type(
        url="https://www.energy.gov/sites/default/files/2023-11/report.pdf",
        domain="energy.gov",
    )
    assert result.source_type == SOURCE_TYPE_GOVERNMENT


def test_repository_host_is_academic_institution() -> None:
    result = classify_source_type(
        url="https://www.collectionscanada.gc.ca/obj/s4/f2/dsk3/OWTU/TC-OWTU-544.pdf",
        domain="collectionscanada.gc.ca",
        title="Techno-Economic Study of CO2 Capture",
    )
    assert result.source_type == SOURCE_TYPE_ACADEMIC_INSTITUTION


def test_explicit_metadata_wins() -> None:
    result = classify_source_type(
        url="https://mdpi.com/x",
        domain="mdpi.com",
        explicit_source_type="Industry Association",
    )
    assert result.source_type == SOURCE_TYPE_INDUSTRY_ASSOCIATION
    assert result.method == "explicit_metadata"


def test_chemical_absorption_mea_span_supported() -> None:
    source = (
        "Amine absorption processes, in particular the monoethanolamine (MEA) "
        "based process, are viable for capturing CO2 from cement flue gas."
    )
    span = find_best_taxonomy_span(source, "chemical_absorption")
    assert span
    assert span_has_taxonomy_support(span, "chemical_absorption")
    assert "mea" in span.casefold() or "amine" in span.casefold()


def test_generic_ccs_only_insufficient_for_chemical_absorption() -> None:
    source = (
        "Many cement plants plan to deploy carbon capture and storage, including "
        "the Brevik CCS project supported by government funding."
    )
    span = find_best_taxonomy_span(source, "chemical_absorption")
    assert span == ""
    assert not span_has_taxonomy_support(source, "chemical_absorption")


def test_selects_better_chemical_absorption_span_elsewhere() -> None:
    source = (
        "Overview of cement decarbonization and CCS projects in Europe.\n\n"
        "Later, the report discusses chemical absorption using aqueous amine "
        "solvents for post-combustion capture at cement kilns.\n\n"
        "Storage and transport are covered separately."
    )
    weak = "Overview of cement decarbonization and CCS projects in Europe."
    best = find_best_taxonomy_span(source, "chemical_absorption", preferred=weak)
    assert "chemical absorption" in best.casefold() or "amine" in best.casefold()
    assert "overview of cement decarbonization" not in best.casefold()


def test_fifty_percent_fly_ash_numeric_support() -> None:
    source = (
        "Raman spectroscopy was used on pastes. Three fly ashes were used as a "
        "cement replacement at the level of 0 and 50% by weight. The pastes were "
        "analyzed over time."
    )
    span = find_best_numeric_span(
        source,
        "50",
        context_terms=["fly ash", "cement", "replacement"],
    )
    assert span
    assert span_supports_numeric_value(
        span, "50", context_terms=["fly ash", "cement"]
    )


def test_numeric_claim_without_percentage_unsupported() -> None:
    source = (
        "Raman spectroscopy has been employed to study pastes made with ordinary "
        "Portland cement (OPC) and fly ash (FA)."
    )
    span = find_best_numeric_span(
        source, "50", context_terms=["fly ash", "OPC"]
    )
    assert span == ""


def test_percent_formatting_variants() -> None:
    source = "Fly ash replacement was 50 percent by weight of binder."
    assert find_best_numeric_span(source, "50%")
    assert find_best_numeric_span(source, "50")
    source2 = "Replacement reached 50 % in the mix design."
    assert find_best_numeric_span(source2, "50")


def test_numeric_with_required_unit() -> None:
    source = "Compressive strength reached 42 MPa at 28 days."
    span = find_best_numeric_span(source, "42", unit="MPa", context_terms=["strength"])
    assert span
    assert "mpa" in span.casefold()
    missing_unit = find_best_numeric_span(
        "Compressive strength reached 42 at 28 days.",
        "42",
        unit="MPa",
        context_terms=["strength"],
    )
    assert missing_unit == ""


def test_align_clears_unsupported_optional_numeric_without_rejecting() -> None:
    source = (
        "The study evaluates recycled volcanic ash as a partial cement replacement "
        "in mortar and concrete manufacturing."
    )
    record = {
        "sub_subcategory_slug": "other_industrial_waste_derived_scms",
        "evidence_text": source,
        "binder_component_1": "Ordinary Portland Cement",
        "binder_component_1_fraction": "50",
        "binder_component_2": "Fly Ash",
        "binder_component_2_fraction": "50",
        "taxonomy_confidence": "Medium",
        "extraction_confidence": "High",
    }
    result = align_record_evidence(record, source_text=source)
    assert result.cleared_fields  # fractions unsupported in this source
    assert record["binder_component_1_fraction"] == ""
    assert record["binder_component_2_fraction"] == ""
    # Record itself retained (optional fields cleared only)
    assert record.get("sub_subcategory_slug") == "other_industrial_waste_derived_scms"


def test_align_replaces_catf_style_evidence_with_amine_span() -> None:
    source = (
        "Overview of the Cement Sector. Many cement production sites in the EU "
        "are making plans to deploy carbon capture and storage, including Norcem’s "
        "Brevik plant in Norway.\n\n"
        "Post-combustion solvent/chemical absorption using amines such as MEA is "
        "among the capture options evaluated for cement plants.\n\n"
        "Transport and storage complete the value chain."
    )
    record = {
        "sub_subcategory_slug": "chemical_absorption",
        "evidence_text": (
            "Many cement production sites in the EU are making plans to deploy "
            "carbon capture and storage, including Norcem’s Brevik plant in Norway."
        ),
        "taxonomy_confidence": "High",
    }
    result = align_record_evidence(record, source_text=source)
    assert result.taxonomy_supported
    assert span_has_taxonomy_support(record["evidence_text"], "chemical_absorption")
    assert "brevik" not in record["evidence_text"].casefold() or "amine" in record[
        "evidence_text"
    ].casefold() or "chemical absorption" in record["evidence_text"].casefold()


def test_align_fly_ash_fifty_percent_updates_evidence() -> None:
    abstract = (
        "Raman spectroscopy has been employed to study the evolution of phases in "
        "pastes made with ordinary Portland cement (OPC) and fly ash (FA). Three "
        "fly ashes with different CaO contents were used as a cement replacement "
        "at the level of 0 and 50% by weight."
    )
    record = {
        "sub_subcategory_slug": "coal_ash",
        "evidence_text": (
            "Raman spectroscopy has been employed to study the evolution of "
            "sulfo-aluminate and hydroxyl phases in pastes made with ordinary "
            "Portland cement (OPC) and fly ash (FA)."
        ),
        "binder_component_1": "Ordinary Portland Cement",
        "binder_component_1_fraction": "50",
        "binder_component_2": "Fly Ash",
        "binder_component_2_fraction": "50",
        "technology_variant": "Fly Ash",
    }
    result = align_record_evidence(record, source_text=abstract)
    assert "50" in record["evidence_text"]
    assert record["binder_component_1_fraction"] == "50"
    assert result.method in {"numeric_span_search", "existing_taxonomy_span", "unchanged"}


def test_citation_twin_uses_aligned_evidence() -> None:
    record = {
        "record_id": "cm_test",
        "category": "Cementitious Materials",
        "subcategory": "Cement-Plant Carbon Capture",
        "subcategory_slug": "cement_plant_carbon_capture",
        "sub_subcategory": "Chemical Absorption",
        "sub_subcategory_slug": "chemical_absorption",
        "technology_variant": "Aqueous Amine Solvent",
        "evidence_origin": "Web",
        "source_id": "web:1",
        "source_type": "Technical Report",
        "source_title": "Test",
        "authors": "",
        "publication_year": "2024",
        "journal_or_site": "",
        "doi": "",
        "source_url": "https://example.org/x",
        "normalized_url": "https://example.org/x",
        "retrieval_timestamp": "",
        "citation": "https://example.org/x",
        "evidence_text": "temporary",
        "evidence_page_or_section": "",
        "extraction_confidence": "High",
    }
    source = (
        "General CCS discussion.\n\n"
        "Chemical absorption with MEA is applied at cement plants for "
        "post-combustion capture.\n"
    )
    align_record_evidence(record, source_text=source)
    cite = citation_from_record(record)
    assert cite["record_id"] == record["record_id"]
    assert cite["evidence_text"] == record["evidence_text"]
    assert span_has_taxonomy_support(cite["evidence_text"], "chemical_absorption")


def test_align_is_deterministic_no_openai_import_side_effect() -> None:
    """Evidence alignment must not require OpenAI / network clients."""
    import importlib

    mod = importlib.import_module("pipeline.cementitious.evidence_alignment")
    source = "MEA amine chemical absorption at a cement plant."
    record = {
        "sub_subcategory_slug": "chemical_absorption",
        "evidence_text": "cement plant project overview",
    }
    mod.align_record_evidence(record, source_text=source)
    assert "amine" in record["evidence_text"].casefold() or "mea" in record[
        "evidence_text"
    ].casefold()
