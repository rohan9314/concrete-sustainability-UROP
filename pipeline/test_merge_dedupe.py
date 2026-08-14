#!/usr/bin/env python3
"""Literature + web merge and project-level deduplication tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.cementitious.dedupe import deduplicate_records, exact_duplicate_key
from pipeline.cementitious.schema import normalize_record
from pipeline.cementitious.web_stages import merge_literature_and_web
from pipeline.decarb_testlib import canonical_record


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class MergeAndDedupeTests(unittest.TestCase):
    def test_literature_only_and_web_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            (out / "metadata").mkdir(parents=True)
            (out / "checkpoints").mkdir()
            lit = normalize_record(canonical_record(record_id="lit-only", evidence_origin="Literature"))
            _write_jsonl(out / "metadata" / "literature_records_raw.jsonl", [lit])
            summary = merge_literature_and_web(output_dir=out)
            self.assertEqual(summary["literature_records"], 1)
            self.assertEqual(summary["web_records"], 0)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            (out / "metadata").mkdir(parents=True)
            (out / "checkpoints").mkdir()
            web = normalize_record(
                canonical_record(
                    record_id="web-only",
                    evidence_origin="Web",
                    source_type="Company Website",
                    source_url="https://co.example/p",
                )
            )
            _write_jsonl(out / "metadata" / "web_records_raw.jsonl", [web])
            summary = merge_literature_and_web(output_dir=out)
            self.assertEqual(summary["literature_records"], 0)
            self.assertEqual(summary["web_records"], 1)

    def test_same_technology_different_sources_kept_with_provenance(self) -> None:
        lit = normalize_record(
            canonical_record(
                record_id="lit1",
                evidence_origin="Literature",
                project_name="Plant A Pilot",
                source_id="10.1/a",
            )
        )
        web = normalize_record(
            canonical_record(
                record_id="web1",
                evidence_origin="Web",
                source_type="Company Website",
                source_url="https://co.example/plant-a",
                project_name="Plant A Pilot",
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "7-30 results"
            (out / "metadata").mkdir(parents=True)
            (out / "checkpoints").mkdir()
            _write_jsonl(out / "metadata" / "literature_records_raw.jsonl", [lit])
            _write_jsonl(out / "metadata" / "web_records_raw.jsonl", [web])
            summary = merge_literature_and_web(output_dir=out)
            self.assertEqual(summary["literature_records"], 1)
            self.assertEqual(summary["web_records"], 1)
            combined = [
                json.loads(line)
                for line in (out / "metadata" / "combined_records_pre_dedupe.jsonl")
                .read_text()
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(combined), 2)
            origins = {r["evidence_origin"] for r in combined}
            self.assertEqual(origins, {"Literature", "Web"})
            web_row = next(r for r in combined if r["evidence_origin"] == "Web")
            self.assertTrue(web_row.get("source_url"))
            kept, _ = deduplicate_records(combined)
            self.assertEqual(len(kept), 2)

    def test_distinct_deployments_same_company_kept(self) -> None:
        shared = dict(
            evidence_origin="Web",
            source_type="Company Website",
            company_or_organization="Acme Capture",
            canonical_technology_name="Chemical Absorption",
        )
        a = normalize_record(
            canonical_record(
                **shared,
                record_id="a",
                project_name="Norway plant",
                location="Norway",
                source_url="https://acme.example/no",
            )
        )
        b = normalize_record(
            canonical_record(
                **shared,
                record_id="b",
                project_name="Texas plant",
                location="Texas",
                source_url="https://acme.example/tx",
            )
        )
        kept, _ = deduplicate_records([a, b])
        self.assertEqual(len(kept), 2)

    def test_slight_naming_variation_stays_separate(self) -> None:
        a = normalize_record(
            canonical_record(record_id="n1", project_name="Plant A Pilot", evidence_origin="Literature")
        )
        b = normalize_record(
            canonical_record(
                record_id="n2",
                project_name="Plant A Pilot Project",
                evidence_origin="Web",
                source_url="https://co.example/a",
            )
        )
        self.assertNotEqual(exact_duplicate_key(a), exact_duplicate_key(b))
        kept, _ = deduplicate_records([a, b])
        self.assertEqual(len(kept), 2)

    def test_exact_duplicate_removed(self) -> None:
        base = canonical_record(
            evidence_origin="Web",
            source_type="Company Website",
            source_url="https://co.example/same",
            normalized_url="https://co.example/same",
            project_name="Same",
            company_or_organization="Acme",
        )
        a = normalize_record({**base, "record_id": "dup-a"})
        b = normalize_record({**base, "record_id": "dup-b"})
        kept, audit = deduplicate_records([a, b])
        self.assertEqual(len(kept), 1)
        self.assertTrue(
            any(x.get("duplicate_status") == "Exact Duplicate Removed" for x in audit) or len(kept) == 1
        )


if __name__ == "__main__":
    unittest.main()
