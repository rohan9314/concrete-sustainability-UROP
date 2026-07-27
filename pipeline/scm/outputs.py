"""Output path helpers for the SCM pipeline (SCM root only)."""

from __future__ import annotations

from pathlib import Path

from pipeline.scm.config import ensure_scm_layout, scm_output_root
from pipeline.scm.seed_categories import ScmSeedCategory

ALL_EVIDENCE_CSV = "scm_all_evidence.csv"
ALL_CITATIONS_CSV = "scm_all_citations.csv"
DISCOVERY_EVIDENCE_CSV = "scm_discovery_evidence.csv"
DISCOVERED_CATEGORIES_CSV = "scm_discovered_categories.csv"
NORMALIZATION_CSV = "scm_material_normalization.csv"
LITERATURE_RECORDS = "literature_records.jsonl"
WEB_RECORDS = "web_records.jsonl"
DISCOVERY_RECORDS = "discovery_records.jsonl"
SCREENING_MERGED = "screening_merged.jsonl"


def scm_layout(output_dir: Path | None = None) -> dict[str, Path]:
    root = output_dir or scm_output_root()
    return ensure_scm_layout(root)


def category_results_path(output_dir: Path, category: ScmSeedCategory) -> Path:
    return output_dir / "csv" / category.results_filename


def category_citations_path(output_dir: Path, category: ScmSeedCategory) -> Path:
    return output_dir / "citations" / category.citations_filename


def all_evidence_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "merged" / ALL_EVIDENCE_CSV


def all_citations_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "merged" / ALL_CITATIONS_CSV


def discovery_evidence_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "discovery" / DISCOVERY_EVIDENCE_CSV


def discovered_categories_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "discovery" / DISCOVERED_CATEGORIES_CSV


def normalization_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "discovery" / NORMALIZATION_CSV


def discovery_records_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "discovery" / DISCOVERY_RECORDS


def screening_merged_path(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    return root / "screening" / SCREENING_MERGED


def literature_path_for_slug(output_dir: Path, slug: str) -> Path:
    return output_dir / "literature" / f"{slug}_literature.jsonl"


def web_path_for_slug(output_dir: Path, slug: str) -> Path:
    return output_dir / "web" / f"{slug}_web.jsonl"


def checkpoint_dir(output_dir: Path | None = None) -> Path:
    root = output_dir or scm_output_root()
    path = root / "checkpoints"
    path.mkdir(parents=True, exist_ok=True)
    return path
