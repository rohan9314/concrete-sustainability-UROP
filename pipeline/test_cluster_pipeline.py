"""Tests for cluster shard planning and JSONL merge helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.carbon_capture_io import merge_ranked_papers, write_ranked_shard
from pipeline.cluster_shards import plan_corpus_shards, shard_for_array_task
from pipeline.schema import FilteredPaper, RankedPaper


def _paper(paper_id: str, rank_score: float) -> RankedPaper:
    base = FilteredPaper(
        paper_id=paper_id,
        relevance_score=1.0,
        title=f"Title {paper_id}",
        abstract="abstract",
    )
    return RankedPaper(**base.model_dump(), rank_score=rank_score)


def test_plan_corpus_shards() -> None:
    shards = plan_corpus_shards(25000, 10000)
    assert len(shards) == 3
    assert shards[0].start == 0 and shards[0].end == 10000
    assert shards[2].start == 20000 and shards[2].end == 25000
    assert shard_for_array_task(shards, 1).label == "10000_20000"


def test_merge_ranked_papers_dedupes_and_top_n() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shard_a = root / "a.jsonl"
        shard_b = root / "b.jsonl"
        write_ranked_shard(
            [_paper("doi:a", 5.0), _paper("doi:b", 8.0)],
            shard_a,
            methodology_slug="amine_absorption",
            shard_start=0,
            shard_end=2,
        )
        write_ranked_shard(
            [_paper("doi:a", 9.0), _paper("doi:c", 7.0)],
            shard_b,
            methodology_slug="amine_absorption",
            shard_start=2,
            shard_end=4,
        )
        merged = merge_ranked_papers([shard_a, shard_b], top_n=2)

    assert [paper.paper_id for paper in merged] == ["doi:a", "doi:b"]
    assert merged[0].rank_score == 9.0


def main() -> int:
    tests = [test_plan_corpus_shards, test_merge_ranked_papers_dedupes_and_top_n]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} cluster helper tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
