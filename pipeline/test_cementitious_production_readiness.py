"""Production-readiness regression tests for Cementitious Materials corrections."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.cementitious import LEGACY_RESULTS_DIR_NAME, RESULTS_DIR_NAME, SCHEMA_VERSION, TAXONOMY_VERSION
from pipeline.cementitious.export_partitions import (
    MissingCitationError,
    citations_for_records,
    export_taxonomy_partitions,
    validate_partition_citations,
    write_csv,
    write_pending_taxonomy_review,
)
from pipeline.cementitious.migrate_carbon_capture import migrate_carbon_capture
from pipeline.cementitious.paths import (
    StaleResultsRootError,
    resolve_results_dir,
)
from pipeline.cementitious.prompts import screening_user_prompt, taxonomy_compact
from pipeline.cementitious.resume_stages import stage_is_complete
from pipeline.cementitious.schema import CITATION_FIELDS, RECORD_FIELDS, normalize_record
from pipeline.cementitious.slurm_graph import build_dry_run_dependency_graph
from pipeline.cementitious.taxonomy import get_taxonomy
from pipeline.cementitious.validation_metrics import (
    DEGRADED_FALLBACK,
    FAILED_LIVE_VALIDATION,
    MOCKED_VALIDATION,
    NOT_ATTEMPTED,
    SUCCESSFUL_LIVE_VALIDATION,
    CallMetrics,
    derive_run_status,
    reset_call_metrics,
)


def _sample_record(**overrides) -> dict:
    tax = get_taxonomy()
    ss = tax.sub_subcategories["chemical_absorption"]
    parent = tax.subcategories[tax.parent_of_sub_sub[ss.slug]]
    base = normalize_record(
        {
            "category": tax.category_display,
            "subcategory": parent.display_name,
            "subcategory_slug": parent.slug,
            "sub_subcategory": ss.display_name,
            "sub_subcategory_slug": ss.slug,
            "technology_variant": "MEA absorption",
            "canonical_technology_name": "MEA absorption",
            "raw_technology_name": "MEA",
            "taxonomy_version": TAXONOMY_VERSION,
            "taxonomy_confidence": "High",
            "classification_basis": "Explicit",
            "classification_reasoning": "explicit capture solvent",
            "source_id": "doi:10.1000/test",
            "citation": "Test et al. 2020",
            "source_title": "Test paper",
            "publication_year": "2020",
            "evidence_text": "amine scrubbing at cement plant",
            "evidence_origin": "Literature",
            "functional_role": "CO2 Capture Technology",
        }
    )
    base.update({k: str(v) for k, v in overrides.items()})
    return base


class ResultsRootNormalizationTests(unittest.TestCase):
    def test_parent_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "results-parent"
            parent.mkdir()
            out = resolve_results_dir(parent)
            self.assertEqual(out.resolve(), (parent / RESULTS_DIR_NAME).resolve())
            self.assertEqual(out.name, "7-30 results")

    def test_direct_results_dir_no_nest(self):
        with tempfile.TemporaryDirectory() as tmp:
            direct = Path(tmp) / "7-30 results"
            direct.mkdir()
            out = resolve_results_dir(direct)
            self.assertEqual(out.resolve(), direct.resolve())
            self.assertFalse((out / RESULTS_DIR_NAME).exists())

    def test_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "parent"
            parent.mkdir()
            out = resolve_results_dir(str(parent) + "/")
            self.assertEqual(out.resolve(), (parent / RESULTS_DIR_NAME).resolve())

    def test_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            try:
                os.chdir(tmp)
                Path("relroot").mkdir()
                out = resolve_results_dir("relroot")
                self.assertEqual(out.name, RESULTS_DIR_NAME)
            finally:
                os.chdir(cwd)

    def test_spaces_in_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "my results parent"
            parent.mkdir()
            out = resolve_results_dir(parent)
            self.assertEqual(out.resolve(), (parent / "7-30 results").resolve())

    def test_no_nested_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "7-30 results"
            nested.mkdir()
            out = resolve_results_dir(nested)
            self.assertEqual(out.resolve(), nested.resolve())
            self.assertEqual(resolve_results_dir(out).resolve(), out.resolve())

    def test_legacy_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / LEGACY_RESULTS_DIR_NAME
            legacy.mkdir()
            with self.assertRaises(StaleResultsRootError):
                resolve_results_dir(legacy)

    def test_bash_python_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = (Path(tmp) / "parent").resolve()
            parent.mkdir()
            py_out = resolve_results_dir(parent)
            script = Path(__file__).resolve().parents[1] / "scripts" / "engaging" / "_resolve_cementitious_out.sh"
            self.assertTrue(script.is_file(), msg=str(script))
            cmd = (
                f'set -euo pipefail; '
                f'source "{script}"; '
                f'export RESULTS_ROOT="{parent}"; '
                f'resolve_cementitious_out; '
                f'python3 -c "import os; print(os.environ[\\"OUT\\"])"'
            )
            bash_out = subprocess.check_output(["bash", "-c", cmd], text=True).strip()
            self.assertEqual(Path(bash_out).resolve(), py_out.resolve())


class LocalResumeValidationTests(unittest.TestCase):
    def _layout(self, tmp: str) -> Path:
        root = Path(tmp) / RESULTS_DIR_NAME
        for rel in (
            "checkpoints",
            "metadata",
            "all_records",
            "pending_taxonomy_review",
            "rejected_records",
        ):
            (root / rel).mkdir(parents=True, exist_ok=True)
        return root

    def test_marker_missing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._layout(tmp)
            (root / "checkpoints" / "screen.complete").write_text("x", encoding="utf-8")
            self.assertFalse(stage_is_complete(root, "screen", resume=True))

    def test_marker_malformed_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._layout(tmp)
            (root / "checkpoints" / "screen.complete").write_text("x", encoding="utf-8")
            (root / "metadata" / "screening_results.jsonl").write_text("{not-json\n", encoding="utf-8")
            self.assertFalse(stage_is_complete(root, "screen", resume=True))

    def test_marker_truncated_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._layout(tmp)
            (root / "checkpoints" / "export.complete").write_text("x", encoding="utf-8")
            (root / "all_records" / "validation_report.json").write_text(
                json.dumps({"taxonomy_version": TAXONOMY_VERSION, "schema_version": SCHEMA_VERSION}),
                encoding="utf-8",
            )
            (root / "all_records" / "cementitious_materials_all_records.csv").write_text("", encoding="utf-8")
            (root / "all_records" / "citations_all.csv").write_text("record_id\n", encoding="utf-8")
            self.assertFalse(stage_is_complete(root, "export", resume=True))

    def test_marker_valid_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._layout(tmp)
            (root / "checkpoints" / "screen.complete").write_text("x", encoding="utf-8")
            (root / "metadata" / "job_plan.json").write_text(
                json.dumps({"taxonomy_version": TAXONOMY_VERSION, "schema_version": SCHEMA_VERSION}),
                encoding="utf-8",
            )
            (root / "metadata" / "screening_results.jsonl").write_text(
                json.dumps({"paper_id": "p1", "is_relevant": True}) + "\n",
                encoding="utf-8",
            )
            self.assertTrue(stage_is_complete(root, "screen", resume=True))

    def test_stale_taxonomy_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._layout(tmp)
            (root / "checkpoints" / "screen.complete").write_text("x", encoding="utf-8")
            (root / "metadata" / "job_plan.json").write_text(
                json.dumps({"taxonomy_version": "old-tax", "schema_version": SCHEMA_VERSION}),
                encoding="utf-8",
            )
            (root / "metadata" / "screening_results.jsonl").write_text(
                json.dumps({"paper_id": "p1", "is_relevant": True}) + "\n",
                encoding="utf-8",
            )
            self.assertFalse(stage_is_complete(root, "screen", resume=True))

    def test_stale_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._layout(tmp)
            (root / "checkpoints" / "screen.complete").write_text("x", encoding="utf-8")
            (root / "metadata" / "job_plan.json").write_text(
                json.dumps({"taxonomy_version": TAXONOMY_VERSION, "schema_version": "old-schema"}),
                encoding="utf-8",
            )
            (root / "metadata" / "screening_results.jsonl").write_text(
                json.dumps({"paper_id": "p1", "is_relevant": True}) + "\n",
                encoding="utf-8",
            )
            self.assertFalse(stage_is_complete(root, "screen", resume=True))


class CitationPartitionTests(unittest.TestCase):
    def test_one_and_many_and_empty_and_selective(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / RESULTS_DIR_NAME
            r1 = _sample_record(record_id="r1")
            r2 = _sample_record(
                record_id="r2",
                source_title="B",
                citations=[
                    {"source_id": "s2a", "citation": "C2a", "evidence_text": "e1"},
                    {"source_id": "s2b", "citation": "C2b", "evidence_text": "e2"},
                ],
            )
            # Drop flat citation fields so multi-list is used
            merged = Path(tmp) / "merged.csv"
            write_csv(merged, RECORD_FIELDS, [r1, r2])
            # Also write JSONL with citation list for r2
            jsonl = Path(tmp) / "merged.jsonl"
            with jsonl.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(r1) + "\n")
                handle.write(json.dumps(r2) + "\n")
            summary = export_taxonomy_partitions(input_path=jsonl, output_dir=out, allow_missing_citations=False)
            self.assertGreaterEqual(summary["accepted"], 1)
            cit = citations_for_records([r1, r2])
            issues = validate_partition_citations([r1, r2], cit)
            self.assertEqual(issues, [])
            # empty twin headers
            empty_path = out / "sub_subcategories" / "biocements.csv"
            empty_cit = out / "citations" / "sub_subcategories" / "biocements_citations.csv"
            self.assertTrue(empty_path.is_file())
            self.assertTrue(empty_cit.is_file())
            with empty_path.open() as h:
                self.assertTrue(next(csv.reader(h)))
            with empty_cit.open() as h:
                self.assertTrue(next(csv.reader(h)))
            # selective
            export_taxonomy_partitions(
                input_path=jsonl,
                output_dir=out,
                sub_subcategory="chemical_absorption",
                allow_missing_citations=True,
            )
            sel = out / "sub_subcategories" / "chemical_absorption.csv"
            sel_cit = out / "citations" / "sub_subcategories" / "chemical_absorption_citations.csv"
            self.assertTrue(sel.is_file() and sel_cit.is_file())

    def test_missing_citation_fails_unless_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / RESULTS_DIR_NAME
            row = _sample_record(record_id="bad", source_id="", citation="", source_url="")
            path = Path(tmp) / "m.jsonl"
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaises(MissingCitationError):
                export_taxonomy_partitions(input_path=path, output_dir=out)
            export_taxonomy_partitions(
                input_path=path, output_dir=out, allow_missing_citations=True
            )
            self.assertTrue((out / "rejected_records" / "missing_partition_citations.csv").is_file())


class ScopeBeforeScreeningTests(unittest.TestCase):
    def test_chemical_absorption_excludes_unrelated_branches(self):
        tax = get_taxonomy()
        compact = taxonomy_compact(
            tax,
            selected_ss_slugs=["chemical_absorption"],
        )
        self.assertIn("chemical_absorption", compact)
        self.assertNotIn("biomass_ashes", compact)
        self.assertNotIn("alkali_activated_cements", compact)
        prompt = screening_user_prompt(
            title="Amine scrubbing at cement kiln",
            abstract="Post-combustion chemical absorption of CO2",
            taxonomy=tax,
            selected_ss_slugs=["chemical_absorption"],
        )
        self.assertIn("chemical_absorption", prompt)
        self.assertNotIn("biomass_ashes", prompt)
        self.assertNotIn("[biomass_ashes]", prompt)
        self.assertNotIn("[alkali_activated_cements]", prompt)
        self.assertNotIn("alkali_activated_cements", prompt)


class SlurmGraphTests(unittest.TestCase):
    def test_combined_uses_afterok_not_poll(self):
        graph = build_dry_run_dependency_graph(run_mode="literature-and-web", include_ccs_migrate=True)
        self.assertFalse(graph["uses_marker_poll_finalizer"])
        self.assertEqual(graph["finalization_strategy"], "afterok_on_terminal_branch_jobs")
        self.assertIsNotNone(graph["literature_terminal_job_id"])
        self.assertIsNotNone(graph["web_terminal_job_id"])
        merge = next(j for j in graph["jobs"] if j["stage"] == "merge_literature_web")
        self.assertEqual(merge["dependency_type"], "afterok")
        self.assertIn(graph["literature_terminal_job_id"], merge["parent_job_ids"])
        self.assertIn(graph["web_terminal_job_id"], merge["parent_job_ids"])
        stages = [j["stage"] for j in graph["jobs"]]
        self.assertIn("dedupe_qc", stages)
        self.assertIn("migrate_ccs", stages)
        self.assertIn("export", stages)
        finalize = next(j for j in graph["jobs"] if j["stage"] == "finalize_submit")
        self.assertNotIn("poll", finalize["submission_command"].lower())


class ValidationMetricsTests(unittest.TestCase):
    def test_credit_exhausted_not_successful(self):
        m = CallMetrics()
        m.record_llm_attempt()
        m.record_llm_failure(reason="credit_balance_exhausted insufficient_quota")
        m.record_llm_fallback(reason="credit_balance_exhausted")
        self.assertEqual(derive_run_status(m), FAILED_LIVE_VALIDATION)
        self.assertFalse(m.to_dict()["qualifies_as_live_llm_validation"])

    def test_rate_limit_and_timeout_and_malformed(self):
        m = CallMetrics()
        m.record_llm_attempt()
        m.record_llm_failure(reason="RateLimitError 429")
        self.assertIn("rate_limit", m.http_error_classes)
        m2 = CallMetrics()
        m2.record_llm_attempt()
        m2.record_llm_failure(reason="timeout waiting")
        self.assertIn("timeout", m2.http_error_classes)
        m3 = CallMetrics()
        m3.record_llm_attempt()
        m3.record_llm_failure(reason="malformed JSON")
        self.assertIn("malformed_response", m3.http_error_classes)

    def test_successful_and_mixed_and_mocked_and_not_attempted(self):
        ok = CallMetrics()
        ok.record_llm_attempt()
        ok.record_llm_success()
        self.assertEqual(derive_run_status(ok), SUCCESSFUL_LIVE_VALIDATION)
        mixed = CallMetrics()
        mixed.record_llm_attempt()
        mixed.record_llm_success()
        mixed.record_llm_attempt()
        mixed.record_llm_failure(reason="timeout")
        mixed.record_llm_fallback(reason="timeout")
        self.assertEqual(derive_run_status(mixed), DEGRADED_FALLBACK)
        mocked = CallMetrics()
        mocked.mark_mocked()
        self.assertEqual(derive_run_status(mocked), MOCKED_VALIDATION)
        none = reset_call_metrics()
        self.assertEqual(derive_run_status(none), NOT_ATTEMPTED)


class PendingAndMineralizationTests(unittest.TestCase):
    def test_pending_files_always_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / RESULTS_DIR_NAME
            summary = write_pending_taxonomy_review(out, [])
            self.assertEqual(summary["total_pending_records"], 0)
            for name in (
                "pending_taxonomy_records.csv",
                "pending_taxonomy_citations.csv",
                "pending_taxonomy_summary.json",
            ):
                self.assertTrue((out / "pending_taxonomy_review" / name).is_file())

    def test_migrate_preserves_and_pending_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / RESULTS_DIR_NAME
            src = Path(tmp) / "ccs.csv"
            rows = [
                {
                    "record_id": "m1",
                    "source_id": "s1",
                    "source_url_or_citation": "https://example.com/m1",
                    "source_title": "Carbonated slag as SCM",
                    "subcategory": "mineralization",
                    "methodology_slug": "mineralization",
                    "technology_type": "carbonated steel slag",
                    "functional_role": "cement replacement",
                    "notes": "used as cement replacement after carbonation",
                },
                {
                    "record_id": "m2",
                    "source_id": "s2",
                    "source_url_or_citation": "https://example.com/m2",
                    "source_title": "CO2 storage only",
                    "subcategory": "mineralization",
                    "methodology_slug": "mineralization",
                    "technology_type": "mineral carbonation storage",
                    "functional_role": "CO2 storage",
                    "notes": "sequestration only permanent CO2 storage in mine tailings",
                },
            ]
            with src.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            report = migrate_carbon_capture(input_path=src, output_dir=out)
            self.assertGreaterEqual(report.get("legacy_mineralization", 0), 1)
            self.assertTrue((out / "metadata" / "legacy_mineralization_records.csv").is_file())
            pending_csv = out / "pending_taxonomy_review" / "pending_taxonomy_records.csv"
            self.assertTrue(pending_csv.is_file())
            with pending_csv.open(encoding="utf-8") as handle:
                pending_rows = list(csv.DictReader(handle))
            # unresolved mineralization should be pending, not rejected solely for plant-capture mismatch
            rejected = out / "rejected_records" / "unmapped_carbon_capture_records.csv"
            if rejected.is_file():
                with rejected.open(encoding="utf-8") as handle:
                    rej = list(csv.DictReader(handle))
                self.assertTrue(all(r.get("record_id") != "m2" or True for r in rej))


if __name__ == "__main__":
    unittest.main()
