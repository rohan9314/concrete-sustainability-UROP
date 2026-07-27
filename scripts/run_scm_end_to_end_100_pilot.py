#!/usr/bin/env python3
"""SCM end-to-end 100-paper local pilot orchestrator (SCM-only; web + discovery)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
load_dotenv(REPO / "backend" / ".env")

corpus = REPO / "filtered_records_rohan.pkl"
os.environ["PICKLE_PATH"] = str(corpus)
os.environ["PAPER_RECORDS_PATH"] = str(corpus)
os.environ["OUTPUT_DIR"] = str(REPO / "outputs")
os.environ["EXTRACTION_CONCURRENCY"] = "2"

assert os.environ.get("OPENAI_API_KEY"), "OPENAI_API_KEY missing"
tv = os.environ.get("TAVILY_API_KEY", "").strip()
assert tv and tv != "YOUR_TAVILY_TOKEN_HERE", "TAVILY_API_KEY missing"
assert corpus.is_file(), f"missing corpus {corpus}"

OUT = REPO / "outputs" / "test" / "scm" / "end_to_end_100"
SAMPLE_SRC = (
    REPO
    / "outputs"
    / "test"
    / "scm"
    / "run_100_seed_categories"
    / "manifests"
)
LOG = OUT / "logs" / "pilot.log"
STAGE_TIMES: dict[str, dict] = {}


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def stage(name: str):
    class _Ctx:
        def __enter__(self):
            self.t0 = time.time()
            log(f"STAGE_START {name}")
            return self

        def __exit__(self, exc_type, exc, tb):
            elapsed = time.time() - self.t0
            status = "FAILED" if exc else "OK"
            STAGE_TIMES[name] = {"status": status, "elapsed_s": round(elapsed, 1)}
            log(f"STAGE_END {name} status={status} elapsed={elapsed:.1f}s")
            return False

    return _Ctx()


def ensure_sample() -> Path:
    manifests = OUT / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    pkl = manifests / "paper_sample_100.pkl"
    meta = manifests / "paper_sample_100.json"
    if pkl.is_file() and meta.is_file():
        log(f"Reuse existing sample {pkl}")
        return pkl
    # Prefer identical seed-42 sample from prior pilot to avoid reloading 5.5GB pickle.
    src_pkl = SAMPLE_SRC / "paper_sample_100.pkl"
    src_json = SAMPLE_SRC / "paper_sample_100.json"
    if src_pkl.is_file() and src_json.is_file():
        shutil.copy2(src_pkl, pkl)
        data = json.loads(src_json.read_text(encoding="utf-8"))
        data["copied_from"] = str(src_json)
        data["pilot_created_at"] = datetime.now(timezone.utc).isoformat()
        data["note"] = (
            "Reused seed=42 reproducible sample from prior local SCM run; "
            "full 5.5GB corpus was NOT reloaded for this pilot's sampling step. "
            "Downstream stages load only this 100-record pickle."
        )
        meta.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log(f"Copied seed-42 sample -> {pkl} (no full-corpus reload)")
        return pkl
    from pipeline.scm.sample import write_sample_artifacts

    write_sample_artifacts(
        output_dir=OUT,
        sample_size=100,
        random_seed=42,
        input_path=corpus,
    )
    log("Created sample via full-corpus load (5.5GB)")
    return pkl


def snapshot_cc(label: str) -> Path:
    from pipeline.scm.config import carbon_capture_output_root

    path = OUT / "validation" / f"cc_timestamps_{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cc = carbon_capture_output_root()
    files = {}
    if cc.exists():
        for p in cc.rglob("*"):
            if p.is_file():
                st = p.stat()
                files[str(p)] = {"mtime": st.st_mtime, "size": st.st_size}
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cc_root": str(cc),
        "cc_exists": cc.exists(),
        "file_count": len(files),
        "files": files,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log(f"CC snapshot {label}: exists={cc.exists()} files={len(files)}")
    return path


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for sub in (
        "manifests",
        "screening",
        "screening/seed_categories",
        "screening/open_discovery",
        "retrieval",
        "literature",
        "web",
        "merged",
        "discovery",
        "normalization",
        "validation",
        "checkpoints",
        "logs",
        "summary",
    ):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    log("=== SCM end-to-end 100-paper pilot ===")
    log("carbon_capture: not invoked")
    log(f"output: {OUT}")
    log(f"concurrency: {os.environ['EXTRACTION_CONCURRENCY']}")

    snapshot_cc("before")
    sample = ensure_sample()
    manifest = json.loads((OUT / "manifests" / "paper_sample_100.json").read_text())
    assert manifest["sample_size"] == 100
    assert len(manifest["paper_ids"]) == 100
    log(f"sample_size={manifest['sample_size']} seed={manifest['random_seed']}")

    from pipeline.scm.runner import ScmRunConfig, merge_all_evidence, run_all_seed_categories, run_discovery, run_seed_category
    from pipeline.scm.seed_categories import list_seed_category_ids
    from pipeline.scm.stages import merge_screening, screen_shard
    from pipeline.scm.__main__ import _normalize_and_cluster

    screening_shard = OUT / "shards" / "screening" / "screening_0_100.jsonl"
    screening_merged = OUT / "screening" / "screening_merged.jsonl"
    open_disc_copy = OUT / "screening" / "open_discovery" / "screening_0_100.jsonl"

    # --- Screening (open-ended SCM relevance over same 100 papers) ---
    if not screening_shard.is_file() or screening_shard.stat().st_size < 10:
        with stage("screen_open_discovery"):
            screen_shard(
                start=0,
                end=100,
                input_path=sample,
                output_path=screening_shard,
                keyword_only=False,
            )
            open_disc_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(screening_shard, open_disc_copy)
    else:
        log("Skip screen (existing shard)")
        STAGE_TIMES["screen_open_discovery"] = {"status": "SKIPPED", "elapsed_s": 0}

    if not screening_merged.is_file():
        with stage("merge_screening"):
            merge_screening([screening_shard], screening_merged)
            shutil.copy2(screening_merged, OUT / "screening_merged.jsonl")
            # Convenience seed-category note: seed runs use the same shared screening filter.
            note = OUT / "screening" / "seed_categories" / "README.txt"
            note.write_text(
                "Seed-category literature runs reuse the shared open-discovery "
                "screening_merged.jsonl as a relevance filter, then apply "
                "per-seed keyword ranking (top_n=20).\n",
                encoding="utf-8",
            )
    else:
        log("Skip merge_screening")
        STAGE_TIMES["merge_screening"] = {"status": "SKIPPED", "elapsed_s": 0}

    # --- Eight seed categories with web ---
    seeds_done = all(
        (OUT / "checkpoints" / f"{slug}_literature.done").is_file()
        and (OUT / "checkpoints" / f"{slug}_web.done").is_file()
        for slug in list_seed_category_ids()
    )
    seed_config = ScmRunConfig(
        slugs=list_seed_category_ids(),
        stage="run-all-seed-categories",
        start=0,
        end=100,
        top_n=20,
        paper_limit=100,
        web_limit=5,
        web_max_results_per_query=3,
        screening_results=str(screening_merged),
        input_path=str(sample),
        output_dir=OUT,
        test_mode=True,
        skip_web=False,
        skip_literature=False,
        run_discovery=False,
        resume=True,
    )
    if not seeds_done:
        with stage("run_all_seed_categories_with_web"):
            # Run one-by-one for clearer progress / failure isolation.
            for slug in list_seed_category_ids():
                t0 = time.time()
                log(f"--- seed {slug} ---")
                try:
                    summary = run_seed_category(seed_config, slug)
                    log(
                        f"DONE {slug} lit={summary.literature_records} "
                        f"web={summary.web_records} merged={summary.merged_records} "
                        f"elapsed={time.time()-t0:.1f}s",
                    )
                except Exception as exc:
                    log(f"FAILED {slug}: {exc}")
                    raise
    else:
        log("Skip seed categories (checkpoints present); re-export via resume path")
        with stage("run_all_seed_categories_with_web"):
            run_all_seed_categories(seed_config)

    # --- Open discovery (top_n=30, web_limit=20) ---
    disc_ckpt = OUT / "checkpoints" / "discovery.done"
    disc_config = ScmRunConfig(
        slugs=[],
        stage="discover",
        start=0,
        end=100,
        top_n=30,
        paper_limit=100,
        web_limit=20,
        web_max_results_per_query=5,
        screening_results=str(screening_merged),
        input_path=str(sample),
        output_dir=OUT,
        test_mode=True,
        skip_web=False,
        skip_literature=False,
        run_discovery=True,
        resume=True,
    )
    if not disc_ckpt.is_file():
        with stage("run_discovery_with_web"):
            run_discovery(disc_config)
    else:
        log("Skip discovery (checkpoint present)")
        with stage("run_discovery_with_web"):
            run_discovery(disc_config)  # resume skip

    # --- Merge ---
    with stage("merge_evidence"):
        merge_all_evidence(
            ScmRunConfig(
                stage="merge-evidence",
                output_dir=OUT,
                test_mode=True,
            ),
        )

    # --- Normalize + LLM cluster ---
    with stage("normalize_and_cluster_llm"):
        rows = _normalize_and_cluster(OUT, heuristic_only=False)
        # Also copy normalization under normalization/
        src_norm = OUT / "discovery" / "scm_material_normalization.csv"
        if src_norm.is_file():
            shutil.copy2(src_norm, OUT / "normalization" / "scm_material_normalization.csv")
        log(f"discovered_categories={len(rows)}")

    # --- Resume test: re-run one completed seed literature stage ---
    with stage("resume_test_slag_cement"):
        before_rows = (OUT / "literature" / "slag_cement_literature.jsonl").read_text()
        before_mtime = (OUT / "literature" / "slag_cement_literature.jsonl").stat().st_mtime
        t0 = time.time()
        run_seed_category(
            ScmRunConfig(
                slugs=["slag_cement"],
                stage="run-seed-category",
                start=0,
                end=100,
                top_n=20,
                paper_limit=100,
                web_limit=5,
                screening_results=str(screening_merged),
                input_path=str(sample),
                output_dir=OUT,
                test_mode=True,
                skip_web=False,
                resume=True,
            ),
            "slag_cement",
        )
        after_rows = (OUT / "literature" / "slag_cement_literature.jsonl").read_text()
        after_mtime = (OUT / "literature" / "slag_cement_literature.jsonl").stat().st_mtime
        resume_result = {
            "stage_rerun": "slag_cement literature+web via run-seed-category --resume",
            "content_unchanged": before_rows == after_rows,
            "mtime_unchanged": before_mtime == after_mtime,
            "elapsed_s": round(time.time() - t0, 2),
        }
        (OUT / "validation" / "resume_test.json").write_text(
            json.dumps(resume_result, indent=2),
            encoding="utf-8",
        )
        log(f"resume_test={resume_result}")

    snapshot_cc("after")
    (OUT / "validation" / "stage_times.json").write_text(
        json.dumps(STAGE_TIMES, indent=2),
        encoding="utf-8",
    )
    log("PILOT_CORE_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
