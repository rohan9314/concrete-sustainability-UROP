"""Local runner stage resume validation (marker alone is insufficient)."""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pipeline.cementitious import SCHEMA_VERSION, TAXONOMY_VERSION

logger = logging.getLogger(__name__)


class ResumeValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StageSpec:
    name: str
    marker_name: str
    required_outputs: tuple[str, ...]
    required_manifests: tuple[str, ...] = ()
    expect_nonempty: bool = True
    require_taxonomy_version: bool = False
    require_schema_version: bool = False
    validate: Callable[[Path, "StageSpec"], None] | None = None


def _validate_jsonl(path: Path, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ResumeValidationError(f"missing output: {path}")
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        if allow_empty:
            return []
        raise ResumeValidationError(f"empty JSONL unexpectedly: {path}")
    for i, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ResumeValidationError(f"malformed JSONL at {path}:{i}: {exc}") from exc
    if not rows and not allow_empty:
        raise ResumeValidationError(f"empty JSONL unexpectedly: {path}")
    return rows


def _validate_csv(path: Path, *, allow_empty: bool = False) -> list[dict[str, str]]:
    if not path.is_file():
        raise ResumeValidationError(f"missing output: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        sample = handle.read(4096)
        if not sample.strip():
            raise ResumeValidationError(f"truncated/empty CSV: {path}")
        handle.seek(0)
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ResumeValidationError(f"CSV missing header: {path}")
        rows = list(reader)
    if not rows and not allow_empty:
        raise ResumeValidationError(f"empty CSV unexpectedly: {path}")
    return rows


def _validate_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ResumeValidationError(f"missing output: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResumeValidationError(f"malformed JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResumeValidationError(f"expected object JSON: {path}")
    return payload


def _check_versions(payload: dict[str, Any], spec: StageSpec) -> None:
    if spec.require_taxonomy_version:
        tv = payload.get("taxonomy_version")
        if tv and tv != TAXONOMY_VERSION:
            raise ResumeValidationError(
                f"stale taxonomy_version={tv!r}; expected {TAXONOMY_VERSION!r}"
            )
    if spec.require_schema_version:
        sv = payload.get("schema_version")
        if sv and sv != SCHEMA_VERSION:
            raise ResumeValidationError(
                f"stale schema_version={sv!r}; expected {SCHEMA_VERSION!r}"
            )


def validate_plan_stage(root: Path, spec: StageSpec) -> None:
    plan = _validate_json(root / "metadata" / "job_plan.json")
    _check_versions(plan, spec)
    sample = root / "metadata" / "working_sample.jsonl"
    if sample.is_file():
        _validate_jsonl(sample, allow_empty=True)


def validate_screen_stage(root: Path, spec: StageSpec) -> None:
    rows = _validate_jsonl(root / "metadata" / "screening_results.jsonl", allow_empty=False)
    for row in rows[:5]:
        if "is_relevant" not in row:
            raise ResumeValidationError("screening row missing is_relevant")
    plan = root / "metadata" / "job_plan.json"
    if plan.is_file():
        _check_versions(_validate_json(plan), spec)


def validate_extract_stage(root: Path, spec: StageSpec) -> None:
    path = root / "metadata" / "extracted_records_raw.jsonl"
    # Extraction may legitimately yield zero rows for tiny/irrelevant samples
    _validate_jsonl(path, allow_empty=True)
    plan = root / "metadata" / "job_plan.json"
    if plan.is_file():
        _check_versions(_validate_json(plan), spec)


def validate_export_stage(root: Path, spec: StageSpec) -> None:
    report = _validate_json(root / "all_records" / "validation_report.json")
    _check_versions(report, spec)
    _validate_csv(root / "all_records" / "cementitious_materials_all_records.csv", allow_empty=True)
    _validate_csv(root / "all_records" / "citations_all.csv", allow_empty=True)
    pending = root / "pending_taxonomy_review" / "pending_taxonomy_records.csv"
    if pending.is_file():
        _validate_csv(pending, allow_empty=True)


STAGE_SPECS: dict[str, StageSpec] = {
    "plan": StageSpec(
        name="plan",
        marker_name="plan.complete",
        required_outputs=("metadata/job_plan.json",),
        require_taxonomy_version=True,
        require_schema_version=True,
        expect_nonempty=True,
        validate=validate_plan_stage,
    ),
    "screen": StageSpec(
        name="screen",
        marker_name="screen.complete",
        required_outputs=("metadata/screening_results.jsonl",),
        require_taxonomy_version=True,
        require_schema_version=True,
        expect_nonempty=True,
        validate=validate_screen_stage,
    ),
    "screen_merge": StageSpec(
        name="screen_merge",
        marker_name="screen_merge.complete",
        required_outputs=("metadata/screening_results.jsonl",),
        expect_nonempty=True,
        validate=validate_screen_stage,
    ),
    "extract": StageSpec(
        name="extract",
        marker_name="extract.complete",
        required_outputs=("metadata/extracted_records_raw.jsonl",),
        require_taxonomy_version=True,
        require_schema_version=True,
        expect_nonempty=False,
        validate=validate_extract_stage,
    ),
    "extract_merge": StageSpec(
        name="extract_merge",
        marker_name="extract_merge.complete",
        required_outputs=("metadata/extracted_records_raw.jsonl",),
        expect_nonempty=False,
        validate=validate_extract_stage,
    ),
    "export": StageSpec(
        name="export",
        marker_name="export.complete",
        required_outputs=(
            "all_records/validation_report.json",
            "all_records/cementitious_materials_all_records.csv",
            "all_records/citations_all.csv",
        ),
        require_taxonomy_version=True,
        require_schema_version=True,
        expect_nonempty=False,
        validate=validate_export_stage,
    ),
}


def stage_is_complete(
    output_dir: Path,
    stage_name: str,
    *,
    resume: bool,
    force: bool = False,
) -> bool:
    """
    Return True only when resume is requested and the stage fully validates.

    Marker alone is never sufficient.
    """
    if force or not resume:
        return False
    spec = STAGE_SPECS.get(stage_name)
    if spec is None:
        marker = output_dir / "checkpoints" / f"{stage_name}.complete"
        return marker.is_file()
    marker = output_dir / "checkpoints" / spec.marker_name
    if not marker.is_file():
        return False
    try:
        for rel in spec.required_outputs:
            path = output_dir / rel
            if not path.is_file():
                raise ResumeValidationError(f"marker present but missing {rel}")
        for rel in spec.required_manifests:
            path = output_dir / rel
            if not path.is_file():
                raise ResumeValidationError(f"marker present but missing manifest {rel}")
        if spec.validate:
            spec.validate(output_dir, spec)
    except Exception as exc:
        logger.warning(
            "RESUME: stage %s marker present but validation failed (%s); rerunning",
            stage_name,
            exc,
        )
        return False
    return True
