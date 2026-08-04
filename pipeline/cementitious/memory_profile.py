"""Tiny local memory-profile helper (never loads the full Engaging corpus).

Usage:
  python -m pipeline.cementitious.memory_profile
  python -m pipeline.cementitious.memory_profile --sample-n 5
"""

from __future__ import annotations

import argparse
import json
import pickle
import tempfile
from pathlib import Path

from pipeline.cementitious.memory import MemoryTelemetry, log_concurrency_settings
from pipeline.cementitious.stages import plan_screen_shards, screen_shard


def _tiny_records(n: int) -> list[dict]:
    rows = []
    for i in range(n):
        rows.append(
            {
                "title": f"Sample SCM binder study {i}",
                "abstract": "Pozzolanic ash used as cement replacement. " * 5,
                "doi": f"10.1000/profile.{i}",
                "year": 2021,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-n", type=int, default=5, help="Tiny fixture size (default 5)")
    parser.add_argument("--shard-size", type=int, default=5)
    args = parser.parse_args(argv)
    sample_n = max(1, min(int(args.sample_n), 50))

    log_concurrency_settings()
    telemetry = MemoryTelemetry(stage="memory_profile")
    telemetry.snapshot("startup")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pkl = root / "tiny.pkl"
        out = root / "out"
        with pkl.open("wb") as handle:
            pickle.dump(_tiny_records(sample_n), handle)
        telemetry.snapshot("after_write_fixture")
        plan_screen_shards(input_path=pkl, output_dir=out, shard_size=args.shard_size)
        telemetry.snapshot("after_plan")
        summary = screen_shard(shard_id=0, output_dir=out, keyword_only=True)
        telemetry.snapshot("after_screen", records_processed=summary.get("actual_processed_count"))

    report = {
        "sample_n": sample_n,
        "note": "Synthetic fixture only; does not load filtered_records_rohan.pkl",
        "telemetry": telemetry.as_dict(),
        "screen_peak_rss_mb": summary.get("peak_rss_mb"),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
