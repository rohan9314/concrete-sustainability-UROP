#!/usr/bin/env python3
"""Tests for literature taxonomy analysis utility (no live LLM/API calls)."""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault(
    "TAXONOMY_PATH",
    str(REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"),
)

from pipeline.cementitious.analyze_literature_taxonomy import (
    analyze,
    is_extraction_artifact,
    is_sample_or_mix_id,
    map_material_name,
    normalize_key,
    normalize_material_name,
    NameAggregate,
    _build_lexicon,
)
from pipeline.cementitious.taxonomy import get_taxonomy, load_taxonomy


def _write_synthetic_csv(path: Path) -> None:
    rows = [
        {
            "Material Name": "Rice Husk Ash",
            "SiO2": "88.5",
            "Al2O3": "1.2",
            "CaO": "1.0",
            "Caption": "Table 2 Oxide composition of rice husk ash SCM",
            "DOI": "10.1000/rha.1",
            "Descriptor": "agricultural residue ash cement replacement",
            "LLM Response": "Rice husk ash used as pozzolanic SCM",
            "Category": "Ash",
        },
        {
            "Material Name": "rice  husk   ash",
            "SiO2": "90.0",
            "Al2O3": "1.0",
            "CaO": "0.8",
            "Caption": "RHA chemical composition",
            "DOI": "10.1000/rha.2",
            "Descriptor": "biomass ash",
            "LLM Response": "pozzolan",
            "Category": "Ash",
        },
        {
            "Material Name": "Silica Fume",
            "SiO2": "95.0",
            "Al2O3": "0.5",
            "CaO": "0.3",
            "Caption": "Microsilica properties",
            "DOI": "10.1000/sf.1",
            "Descriptor": "condensed silica fume",
            "LLM Response": "SCM silica fume",
            "Category": "Fume",
        },
        {
            "Material Name": "FA",
            "SiO2": "55.0",
            "Al2O3": "25.0",
            "CaO": "5.0",
            "Caption": "Fly ash Class F composition from coal combustion",
            "DOI": "10.1000/fa.1",
            "Descriptor": "fly ash",
            "LLM Response": "coal fly ash SCM",
            "Category": "Ash",
        },
        {
            "Material Name": "FA",
            "SiO2": "50.0",
            "Al2O3": "20.0",
            "CaO": "8.0",
            "Caption": "Fine aggregate grading curve",
            "DOI": "10.1000/fa.agg",
            "Descriptor": "aggregate",
            "LLM Response": "fine aggregate only",
            "Category": "Aggregate",
        },
        {
            "Material Name": "S1",
            "SiO2": "40.0",
            "Al2O3": "20.0",
            "CaO": "15.0",
            "Caption": "Mix design table sample S1",
            "DOI": "10.1000/mix.1",
            "Descriptor": "sample",
            "LLM Response": "mixture S1",
            "Category": "Mix",
        },
        {
            "Material Name": "M3",
            "SiO2": "",
            "Al2O3": "",
            "CaO": "",
            "Caption": "Mixture M3 compressive strength",
            "DOI": "10.1000/mix.2",
            "Descriptor": "",
            "LLM Response": "",
            "Category": "Mix",
        },
        {
            "Material Name": "1027A",
            "SiO2": "30",
            "Al2O3": "10",
            "CaO": "40",
            "Caption": "Specimen 1027A",
            "DOI": "10.1000/mix.3",
            "Descriptor": "",
            "LLM Response": "",
            "Category": "Sample",
        },
        {
            "Material Name": "Literature",
            "SiO2": "",
            "Al2O3": "",
            "CaO": "",
            "Caption": "Heading row",
            "DOI": "",
            "Descriptor": "",
            "LLM Response": "",
            "Category": "",
        },
        {
            "Material Name": "Metakaolin",
            "SiO2": "55",
            "Al2O3": "40",
            "CaO": "0.5",
            "Caption": "Calcined clay metakaolin SCM",
            "DOI": "10.1000/mk.1",
            "Descriptor": "calcined kaolin",
            "LLM Response": "metakaolin pozzolan",
            "Category": "Clay",
        },
        {
            "Material Name": "GGBFS",
            "SiO2": "35",
            "Al2O3": "12",
            "CaO": "42",
            "Caption": "Ground granulated blast furnace slag",
            "DOI": "10.1000/slag.1",
            "Descriptor": "slag cement",
            "LLM Response": "GGBS binder",
            "Category": "Slag",
        },
        {
            "Material Name": "Exotic Moon Dust Binder",
            "SiO2": "20",
            "Al2O3": "10",
            "CaO": "5",
            "Caption": "Novel lunar regolith cementitious trial",
            "DOI": "10.1000/exotic.1",
            "Descriptor": "unrelated novel material",
            "LLM Response": "not in taxonomy",
            "Category": "Other",
        },
        {
            "Material Name": "Smith et al.",
            "SiO2": "",
            "Al2O3": "",
            "CaO": "",
            "Caption": "Author column mis-extracted",
            "DOI": "10.1000/bad.1",
            "Descriptor": "",
            "LLM Response": "",
            "Category": "",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class NormalizeTests(unittest.TestCase):
    def test_normalize_whitespace_and_case(self):
        self.assertEqual(normalize_material_name("  rice  husk   ash "), "rice husk ash")
        self.assertEqual(normalize_key("Rice-Husk Ash"), normalize_key("rice husk ash"))

    def test_sample_ids(self):
        self.assertTrue(is_sample_or_mix_id("S1"))
        self.assertTrue(is_sample_or_mix_id("M3"))
        self.assertTrue(is_sample_or_mix_id("V6a"))
        self.assertTrue(is_sample_or_mix_id("1027A"))
        self.assertFalse(is_sample_or_mix_id("Silica Fume"))
        self.assertFalse(is_sample_or_mix_id("Fly Ash"))

    def test_artifacts(self):
        self.assertTrue(is_extraction_artifact("Literature"))
        self.assertTrue(is_extraction_artifact("Table"))
        self.assertTrue(is_extraction_artifact("Smith et al."))
        self.assertFalse(is_extraction_artifact("Rice Husk Ash"))


class MappingTests(unittest.TestCase):
    def setUp(self):
        get_taxonomy.cache_clear()
        self.tax = load_taxonomy(
            REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"
        )
        self.lex = _build_lexicon(self.tax)

    def test_maps_rice_husk_ash(self):
        agg = NameAggregate(
            raw_name="Rice Husk Ash",
            normalized_name="Rice Husk Ash",
            frequency=2,
            dois={"10.1/a"},
            categories=__import__("collections").Counter({"Ash": 2}),
            captions=["rice husk ash SCM"],
            descriptors=["biomass"],
        )
        m = map_material_name(agg, lexicon=self.lex, taxonomy=self.tax)
        self.assertEqual(m.proposed_sub_subcategory_slug, "biomass_ashes")
        self.assertEqual(m.confidence, "High")
        self.assertEqual(m.status, "mapped")

    def test_does_not_classify_from_oxides_alone(self):
        # High SiO2 but name is unresolved exotic — must not map to silica fume via oxides
        agg = NameAggregate(
            raw_name="Exotic Moon Dust Binder",
            normalized_name="Exotic Moon Dust Binder",
            frequency=1,
            dois={"10.1/x"},
            categories=__import__("collections").Counter({"Other": 1}),
            captions=["novel lunar trial"],
            oxide_rows=[{"SiO2": "95.0", "CaO": "0.2"}],
        )
        m = map_material_name(agg, lexicon=self.lex, taxonomy=self.tax)
        self.assertNotEqual(m.proposed_sub_subcategory_slug, "silica_fume")
        self.assertEqual(m.status, "unresolved")

    def test_ambiguous_fa_without_enough_context_stays_cautious(self):
        agg = NameAggregate(
            raw_name="FA",
            normalized_name="FA",
            frequency=1,
            dois={"10.1/fa"},
            categories=__import__("collections").Counter({"Ash": 1}),
            captions=["composition table FA"],
            descriptors=[""],
        )
        m = map_material_name(agg, lexicon=self.lex, taxonomy=self.tax)
        self.assertIn(m.status, {"ambiguous", "unresolved"})
        self.assertEqual(m.human_review_required, "yes")


class AnalyzeEndToEndTests(unittest.TestCase):
    def setUp(self):
        get_taxonomy.cache_clear()
        self.tax = load_taxonomy(
            REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"
        )

    def test_full_analysis_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "lit.csv"
            out = tmp_path / "analysis"
            syn = tmp_path / "generated_literature_synonyms.yaml"
            _write_synthetic_csv(csv_path)

            # Ensure no accidental OpenAI/Tavily calls
            with mock.patch.dict(os.environ, {}, clear=False):
                profile = analyze(
                    input_path=csv_path,
                    taxonomy=self.tax,
                    output_dir=out,
                    write_synonym_file=True,
                    synonym_output=syn,
                    use_llm=False,
                )

            self.assertFalse(profile["taxonomy_overwritten"])
            self.assertGreater(profile["total_rows"], 10)
            self.assertIn("coverage", profile)

            required = [
                "observed_material_names.csv",
                "proposed_synonym_mappings.csv",
                "unresolved_material_names.csv",
                "ambiguous_abbreviations.csv",
                "category_crosswalk.csv",
                "proposed_technology_variants.csv",
                "taxonomy_coverage_summary.csv",
                "material_frequency_by_source.csv",
                "data_quality_issues.csv",
            ]
            for name in required:
                self.assertTrue((out / name).is_file(), name)

            observed = list(
                csv.DictReader((out / "observed_material_names.csv").open(encoding="utf-8"))
            )
            by_name = {r["normalized_name"].casefold(): r for r in observed}
            self.assertIn("rice husk ash", by_name)
            self.assertEqual(by_name["rice husk ash"]["proposed_sub_subcategory_slug"], "biomass_ashes")
            self.assertEqual(by_name["s1"]["status"], "sample_id")
            self.assertEqual(by_name["literature"]["status"], "artifact")

            # Synonym file pending, does not overwrite taxonomy
            self.assertTrue(syn.is_file())
            text = syn.read_text(encoding="utf-8")
            self.assertIn("pending_approval", text)
            self.assertIn("overwrite_approved_taxonomy: false", text)

            # Approved taxonomy untouched
            tax_path = REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"
            self.assertTrue(tax_path.is_file())

            coverage = {
                r["metric"]: r
                for r in csv.DictReader(
                    (out / "taxonomy_coverage_summary.csv").open(encoding="utf-8")
                )
            }
            self.assertIn("percent_confidently_mapped", coverage)
            self.assertIn("percent_unresolved", coverage)
            self.assertIn("percent_probable_extraction_artifacts", coverage)

    def test_cli_entrypoint(self):
        from pipeline.cementitious.analyze_literature_taxonomy import main
        import io
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            csv_path = tmp_path / "lit.csv"
            out = tmp_path / "out"
            syn = tmp_path / "syn.yaml"
            _write_synthetic_csv(csv_path)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = main(
                    [
                        "--input",
                        str(csv_path),
                        "--taxonomy",
                        str(REPO_ROOT / "config" / "cementitious_materials_taxonomy.json"),
                        "--output",
                        str(out),
                        "--synonym-output",
                        str(syn),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertTrue((out / "observed_material_names.csv").is_file())


if __name__ == "__main__":
    unittest.main()
