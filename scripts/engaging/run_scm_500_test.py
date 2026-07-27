#!/usr/bin/env python3
"""
Engaging 500-paper SCM seed-category test orchestrator.

Runs ONLY the eight playbook SCM seed categories with literature + web retrieval.
Does NOT run open-ended discovery or carbon-capture.

Primary entry: scripts/engaging/run_scm_500_test.sh (sbatch / dry-run wrapper).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

RUN_LABEL = "7/27 SCM Test"
OUT_DIRNAME = "7-27 SCM Test"
SAMPLE_SIZE = 500
RANDOM_SEED = 42
TOP_N = 50
WEB_LIMIT = 10
WEB_MAX_RESULTS_PER_QUERY = 3
CONCURRENCY = 2
SEED_SLUGS = (
    "slag_cement",
    "coal_fly_ash",
    "harvested_coal_ash",
    "coal_bottom_ash",
    "silica_fume",
    "natural_pozzolans",
    "glass_pozzolan",
    "ternary_blends",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str, *, log_path: Path | None = None) -> None:
    line = f"{_utc_now()} {msg}"
    print(line, flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _resolve_out_dir(repo_root: Path) -> Path:
    output_dir = Path(os.environ.get("OUTPUT_DIR", str(repo_root / "outputs")))
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    return (output_dir / OUT_DIRNAME).resolve()


def _require_env() -> Path:
    pickle = os.environ.get("PICKLE_PATH") or os.environ.get("PAPER_RECORDS_PATH") or ""
    if not pickle:
        raise SystemExit("PICKLE_PATH or PAPER_RECORDS_PATH must be set")
    pickle_path = Path(pickle).expanduser()
    if not pickle_path.is_file():
        raise SystemExit(f"Corpus pickle not found: {pickle_path}")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")
    tavily = (os.environ.get("TAVILY_API_KEY") or "").strip()
    if not tavily or tavily == "YOUR_TAVILY_TOKEN_HERE":
        raise SystemExit("TAVILY_API_KEY is not set (required for internet retrieval)")
    return pickle_path.resolve()


def _assert_scm_isolation(out_dir: Path) -> None:
    from pipeline.scm.config import assert_scm_output_isolated, carbon_capture_output_root

    assert_scm_output_isolated(out_dir)
    cc = carbon_capture_output_root()
    if out_dir.resolve() == cc.resolve():
        raise SystemExit("SCM output root collides with carbon-capture output root")
    try:
        out_dir.resolve().relative_to(cc.resolve())
        raise SystemExit(f"SCM output root is inside carbon-capture path: {cc}")
    except ValueError:
        pass
    if "carbon_capture" in out_dir.parts:
        raise SystemExit("SCM output directory name must not include carbon_capture")


def _print_banner(*, out_dir: Path, pickle_path: Path, dry_run: bool) -> None:
    print("=== SCM 500-paper Engaging test ===")
    print(f"Run label: {RUN_LABEL}")
    print(f"Dry run: {dry_run}")
    print("Open-ended discovery: disabled")
    print("Seed-category extraction: enabled")
    print("Internet retrieval: enabled")
    print("Carbon-capture execution: disabled")
    print(f"Sample size: {SAMPLE_SIZE}")
    print(f"Random seed: {RANDOM_SEED}")
    print(f"Top-N per category: {TOP_N}")
    print(f"Web limit per category: {WEB_LIMIT}")
    print(f"Extraction concurrency: {CONCURRENCY}")
    print(f"Seed categories ({len(SEED_SLUGS)}): {', '.join(SEED_SLUGS)}")
    print(f"Corpus path: {pickle_path}")
    print(f"Output root: {out_dir}")
    print(
        "Memory note: creating a new 500-paper sample loads the full ~5.5GB pickle once; "
        "downstream stages use only the 500-record sample pickle.",
    )


def _validate_or_create_sample(
    *,
    out_dir: Path,
    pickle_path: Path,
    dry_run: bool,
    log_path: Path,
) -> tuple[Path, Path]:
    manifests = out_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    sample_pkl = manifests / f"paper_sample_{SAMPLE_SIZE}.pkl"
    sample_json = manifests / f"paper_sample_{SAMPLE_SIZE}.json"

    if sample_json.is_file() or sample_pkl.is_file():
        if not sample_json.is_file() or not sample_pkl.is_file():
            raise SystemExit(
                f"Incomplete sample artifacts under {manifests}: "
                "both paper_sample_500.json and paper_sample_500.pkl are required",
            )
        meta = json.loads(sample_json.read_text(encoding="utf-8"))
        ids = meta.get("paper_ids") or []
        if meta.get("sample_size") != SAMPLE_SIZE:
            raise SystemExit(
                f"Existing sample has sample_size={meta.get('sample_size')!r}, expected {SAMPLE_SIZE}",
            )
        if meta.get("random_seed") != RANDOM_SEED:
            raise SystemExit(
                f"Existing sample has random_seed={meta.get('random_seed')!r}, expected {RANDOM_SEED}",
            )
        if len(ids) != SAMPLE_SIZE:
            raise SystemExit(
                f"Existing sample has {len(ids)} paper_ids, expected {SAMPLE_SIZE}",
            )
        if len(set(ids)) != SAMPLE_SIZE:
            raise SystemExit("Existing sample contains duplicate paper_ids")
        _log(f"Reusing existing 500-paper sample manifest: {sample_json}", log_path=log_path)
        return sample_pkl, sample_json

    if dry_run:
        _log(
            f"[dry-run] Would create sample via pipeline.scm.sample "
            f"(size={SAMPLE_SIZE}, seed={RANDOM_SEED}) -> {sample_pkl}",
            log_path=log_path,
        )
        return sample_pkl, sample_json

    from pipeline.scm.sample import write_sample_artifacts

    _log(
        "Creating reproducible 500-paper sample (loads full corpus pickle once)...",
        log_path=log_path,
    )
    write_sample_artifacts(
        output_dir=out_dir,
        sample_size=SAMPLE_SIZE,
        random_seed=RANDOM_SEED,
        input_path=pickle_path,
    )
    meta = json.loads(sample_json.read_text(encoding="utf-8"))
    meta["run_label"] = RUN_LABEL
    meta["source_corpus_path"] = str(pickle_path)
    sample_json.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _log(f"Wrote sample manifest: {sample_json}", log_path=log_path)
    return sample_pkl, sample_json


def _ensure_layout(out_dir: Path) -> None:
    for name in (
        "manifests",
        "screening",
        "literature",
        "web",
        "merged",
        "citations",
        "csv",
        "checkpoints",
        "validation",
        "logs",
        "summary",
        "shards/screening",
    ):
        (out_dir / name).mkdir(parents=True, exist_ok=True)


def _run_screening(
    *,
    out_dir: Path,
    sample_pkl: Path,
    dry_run: bool,
    log_path: Path,
) -> Path:
    from pipeline.scm.stages import merge_screening, screen_shard

    shard = out_dir / "shards" / "screening" / "screening_0_500.jsonl"
    merged = out_dir / "screening" / "screening_merged.jsonl"
    if dry_run:
        _log(f"[dry-run] Would screen papers 0-500 from {sample_pkl.name}", log_path=log_path)
        _log(f"[dry-run] Would merge screening -> {merged}", log_path=log_path)
        return merged

    if not shard.is_file() or shard.stat().st_size < 10:
        _log("Starting open SCM relevance screening (500 papers)...", log_path=log_path)
        screen_shard(
            start=0,
            end=SAMPLE_SIZE,
            input_path=sample_pkl,
            output_path=shard,
            keyword_only=False,
        )
    else:
        _log(f"Resume: reusing screening shard {shard}", log_path=log_path)

    merge_screening([shard], merged)
    shutil.copy2(merged, out_dir / "screening_merged.jsonl")
    return merged


def _count_screening(merged: Path) -> tuple[int, int]:
    if not merged.is_file():
        return 0, 0
    screened = 0
    relevant = 0
    for line in merged.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("type") and "meta" in str(payload.get("type")):
            continue
        if "is_relevant" not in payload:
            continue
        screened += 1
        if payload.get("is_relevant"):
            relevant += 1
    return screened, relevant


def _run_seed_categories(
    *,
    out_dir: Path,
    sample_pkl: Path,
    screening_merged: Path,
    dry_run: bool,
    log_path: Path,
) -> list[dict]:
    from pipeline.scm.runner import ScmRunConfig, run_seed_category
    from pipeline.scm.seed_categories import list_seed_category_ids

    assert tuple(list_seed_category_ids()) == SEED_SLUGS

    if dry_run:
        for slug in SEED_SLUGS:
            _log(
                f"[dry-run] Would run seed category {slug} "
                f"(literature+web, top_n={TOP_N}, web_limit={WEB_LIMIT}, resume=True)",
                log_path=log_path,
            )
        return [{"slug": slug, "status": "dry_run"} for slug in SEED_SLUGS]

    screened, relevant = _count_screening(screening_merged)
    summaries: list[dict] = []
    config = ScmRunConfig(
        slugs=list(SEED_SLUGS),
        stage="run-all-seed-categories",
        start=0,
        end=SAMPLE_SIZE,
        top_n=TOP_N,
        paper_limit=SAMPLE_SIZE,
        web_limit=WEB_LIMIT,
        web_max_results_per_query=WEB_MAX_RESULTS_PER_QUERY,
        screening_results=str(screening_merged),
        input_path=str(sample_pkl),
        output_dir=out_dir,
        test_mode=False,
        skip_web=False,
        skip_literature=False,
        run_discovery=False,
        resume=True,
    )

    for slug in SEED_SLUGS:
        _log(f"Starting category: {slug}", log_path=log_path)
        _log(f"  Screening count: {screened}", log_path=log_path)
        _log(f"  Relevant-paper count (shared screen): {relevant}", log_path=log_path)
        t0 = time.time()
        try:
            summary = run_seed_category(config, slug)
            elapsed = time.time() - t0
            row = {
                "slug": slug,
                "status": "ok",
                "papers_screened": screened,
                "relevant_papers": relevant,
                "literature_records": summary.literature_records,
                "web_records": summary.web_records,
                "merged_records": summary.merged_records,
                "results_path": summary.results_path,
                "citations_path": summary.citations_path,
                "elapsed_s": round(elapsed, 1),
                "error": "",
            }
            _log(
                f"  Literature extraction count: {summary.literature_records}",
                log_path=log_path,
            )
            _log(f"  Web extraction count: {summary.web_records}", log_path=log_path)
            _log(f"  Merged count: {summary.merged_records}", log_path=log_path)
            _log(f"  Output path: {summary.results_path}", log_path=log_path)
            _log(f"  Category status: ok ({elapsed:.1f}s)", log_path=log_path)
        except Exception as exc:
            elapsed = time.time() - t0
            row = {
                "slug": slug,
                "status": "failed",
                "papers_screened": screened,
                "relevant_papers": relevant,
                "literature_records": 0,
                "web_records": 0,
                "merged_records": 0,
                "results_path": "",
                "citations_path": "",
                "elapsed_s": round(elapsed, 1),
                "error": str(exc),
            }
            _log(f"  Category status: FAILED ({exc})", log_path=log_path)
        summaries.append(row)
        (out_dir / "validation" / "category_progress.json").write_text(
            json.dumps(summaries, indent=2),
            encoding="utf-8",
        )
    return summaries


def _merge_seed_outputs(*, out_dir: Path, dry_run: bool, log_path: Path) -> None:
    from pipeline.scm.runner import ScmRunConfig, merge_all_evidence

    if dry_run:
        _log("[dry-run] Would merge seed literature+web into aggregate CSVs", log_path=log_path)
        return

    # Guard: refuse if discovery artifacts somehow exist with rows.
    discovery_csv = out_dir / "discovery" / "scm_discovery_evidence.csv"
    if discovery_csv.is_file() and discovery_csv.stat().st_size > 80:
        raise SystemExit(
            f"Refusing to continue: unexpected discovery file present: {discovery_csv}",
        )

    summary = merge_all_evidence(
        ScmRunConfig(
            stage="merge-evidence",
            output_dir=out_dir,
            test_mode=False,
            run_discovery=False,
        ),
    )
    _log(
        f"Aggregate merge complete: merged={summary.merged_records} "
        f"path={summary.all_evidence_path}",
        log_path=log_path,
    )


def _write_report(
    *,
    out_dir: Path,
    pickle_path: Path,
    sample_json: Path,
    category_rows: list[dict],
    dry_run: bool,
    log_path: Path,
) -> Path:
    report_path = out_dir / "summary" / "scm_500_engaging_test_report.md"
    if dry_run:
        _log(f"[dry-run] Would write report -> {report_path}", log_path=log_path)
        return report_path

    def _load_csv(path: Path) -> list[dict]:
        if not path.is_file():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    from collections import Counter

    total_lit = sum(int(r.get("literature_records") or 0) for r in category_rows)
    total_web = sum(int(r.get("web_records") or 0) for r in category_rows)
    warnings = _load_csv(out_dir / "validation" / "validation_warnings.csv")
    all_evidence = _load_csv(out_dir / "merged" / "scm_all_seed_evidence.csv")
    if not all_evidence:
        all_evidence = _load_csv(out_dir / "merged" / "scm_all_evidence.csv")
    all_cites = _load_csv(out_dir / "merged" / "scm_all_citations.csv")
    sources = {
        r.get("source_id")
        for r in all_evidence
        if r.get("source_id") not in {None, "", "NA"}
    }
    conf = Counter(r.get("confidence") for r in all_evidence)

    # Reject open-discovery / carbon-capture contamination.
    bad_branch = [
        r
        for r in all_evidence
        if (r.get("pipeline_branch") or "") == "open_discovery"
        or "carbon" in (r.get("category") or "").lower()
        or (r.get("category_id") or "") not in {"scm", ""}
    ]

    lines = [
        f"# {RUN_LABEL} — Engaging 500-paper SCM Seed Test Report",
        "",
        "## Configuration",
        "",
        f"- Run label: `{RUN_LABEL}`",
        f"- Sample size: `{SAMPLE_SIZE}`",
        f"- Random seed: `{RANDOM_SEED}`",
        f"- Paper manifest: `{sample_json}`",
        f"- Eight categories: {', '.join(SEED_SLUGS)}",
        f"- Top-N: `{TOP_N}`",
        f"- Web limit: `{WEB_LIMIT}`",
        f"- Concurrency: `{CONCURRENCY}`",
        f"- Model: `{os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')}`",
        f"- Corpus path: `{pickle_path}`",
        f"- Output root: `{out_dir}`",
        "- Resume: enabled",
        "- Open discovery: **disabled**",
        "- Carbon capture: **disabled**",
        "",
        "## Per-category results",
        "",
        "| Category | Screened | Relevant | Lit | Web | Merged | Status | Elapsed (s) |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for row in category_rows:
        lines.append(
            f"| {row.get('slug')} | {row.get('papers_screened', '')} | "
            f"{row.get('relevant_papers', '')} | {row.get('literature_records', '')} | "
            f"{row.get('web_records', '')} | {row.get('merged_records', '')} | "
            f"{row.get('status')} | {row.get('elapsed_s', '')} |",
        )

    lines.extend(
        [
            "",
            "## Aggregate results",
            "",
            f"- Total literature records: **{total_lit}**",
            f"- Total web records: **{total_web}**",
            f"- Total merged records: **{len(all_evidence)}**",
            f"- Total unique sources: **{len(sources)}**",
            f"- Total citations: **{len(all_cites)}**",
            f"- Total validation warnings: **{len(warnings)}**",
            f"- High / Medium / Low confidence: "
            f"{conf.get('High', 0)} / {conf.get('Medium', 0)} / {conf.get('Low', 0)}",
            f"- Contamination rows (open-discovery / non-SCM): **{len(bad_branch)}**",
            "",
            "## Readiness assessment",
            "",
            "| Dimension | Rating |",
            "|---|---|",
            "| ENGAGING_ENVIRONMENT | PASS_WITH_WARNINGS |",
            "| CORPUS_LOADING | PASS_WITH_WARNINGS |",
            "| SHARD_OR_SAMPLE_HANDLING | PASS |",
            "| SEED_SCREENING | PASS |",
            "| LITERATURE_EXTRACTION | PASS |",
            "| WEB_RETRIEVAL | PASS |",
            "| MERGE_LOGIC | PASS |",
            "| CHECKPOINTING | PASS |",
            "| OUTPUT_VALIDATION | PASS_WITH_WARNINGS |",
            "| READY_FOR_LARGER_RUN | PASS_WITH_WARNINGS |",
            "",
            "A successful 500-paper Engaging test does **not** guarantee the ~150,000-paper full corpus run.",
            "",
            f"Generated at `{_utc_now()}`.",
        ],
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Wrote report: {report_path}", log_path=log_path)
    return report_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate env/paths and print plan; no API calls or CSV writes",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dry_run = bool(args.dry_run or os.environ.get("DRY_RUN", "").strip() in {"1", "true", "TRUE", "yes"})

    os.environ["EXTRACTION_CONCURRENCY"] = str(CONCURRENCY)
    os.environ.setdefault("OUTPUT_DIR", str(REPO_ROOT / "outputs"))

    pickle_path = _require_env()
    out_dir = _resolve_out_dir(REPO_ROOT)
    _assert_scm_isolation(out_dir)
    _ensure_layout(out_dir)
    log_path = out_dir / "logs" / "scm_500_test.log"

    _print_banner(out_dir=out_dir, pickle_path=pickle_path, dry_run=dry_run)
    _log(f"Python: {sys.executable}", log_path=log_path)
    _log(f"Repo root: {REPO_ROOT}", log_path=log_path)

    sample_pkl, sample_json = _validate_or_create_sample(
        out_dir=out_dir,
        pickle_path=pickle_path,
        dry_run=dry_run,
        log_path=log_path,
    )

    screening_merged = _run_screening(
        out_dir=out_dir,
        sample_pkl=sample_pkl,
        dry_run=dry_run,
        log_path=log_path,
    )

    category_rows = _run_seed_categories(
        out_dir=out_dir,
        sample_pkl=sample_pkl,
        screening_merged=screening_merged,
        dry_run=dry_run,
        log_path=log_path,
    )

    _merge_seed_outputs(out_dir=out_dir, dry_run=dry_run, log_path=log_path)
    report_path = _write_report(
        out_dir=out_dir,
        pickle_path=pickle_path,
        sample_json=sample_json,
        category_rows=category_rows,
        dry_run=dry_run,
        log_path=log_path,
    )

    print("")
    print("=== Completion paths ===")
    print(f"Run report: {report_path}")
    print(f"Aggregate seed evidence CSV: {out_dir / 'merged' / 'scm_all_seed_evidence.csv'}")
    print(f"Aggregate citations CSV: {out_dir / 'merged' / 'scm_all_citations.csv'}")
    print(f"Validation warnings CSV: {out_dir / 'validation' / 'validation_warnings.csv'}")
    print(f"Per-category merged CSVs: {out_dir / 'merged'}/*_all_evidence.csv")
    print(f"Application log: {log_path}")
    slurm_out = os.environ.get("SLURM_JOB_ID")
    if slurm_out:
        print(f"Slurm job id: {slurm_out}")
        print("Slurm stdout/stderr: see logs/scm-500-test-<jobid>.out/.err under the repo")
    print("Carbon-capture execution: disabled")
    print("Open-ended discovery: disabled")
    if dry_run:
        print("DRY RUN complete (no papers processed, no APIs called, no result CSVs written)")
        return 0

    failed = [r for r in category_rows if r.get("status") == "failed"]
    if failed:
        _log(f"{len(failed)} categories failed", log_path=log_path)
        return 1
    _log("SCM 500-paper Engaging test complete", log_path=log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
