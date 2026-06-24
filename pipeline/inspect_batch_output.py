#!/usr/bin/env python3
"""Summarize ranked-paper output from pipeline/run_batch.py."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a run_batch JSONL output file.")
    parser.add_argument("path", type=str, help="Path to JSONL output (e.g. outputs/test_0_100.jsonl)")
    parser.add_argument("--top", type=int, default=10, help="Number of top titles to show")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    path = Path(args.path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    shard_meta: dict = {}
    papers: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("type") == "shard_meta":
            shard_meta = payload
        elif payload.get("type") == "ranked_paper":
            papers.append(payload)

    if shard_meta:
        print("Shard metadata:")
        print(f"  query: {shard_meta.get('query') or '(none)'}")
        print(f"  technology_name: {shard_meta.get('technology_name') or '(none)'}")
        print(f"  slice: [{shard_meta.get('start')}, {shard_meta.get('end')})")
        print(f"  loaded/filtered/ranked: {shard_meta.get('loaded')}/{shard_meta.get('filtered')}/{shard_meta.get('ranked')}")

    if not papers:
        print("No ranked_paper records found.")
        return 0

    papers.sort(key=lambda item: item.get("rank_score", item.get("relevance_score", 0)), reverse=True)

    label_counts = Counter(p.get("relevance_label", "Unknown") for p in papers)
    year_source_counts = Counter(p.get("year_source", "unknown") for p in papers)

    print(f"\nRanked papers: {len(papers)}")
    print("\nRelevance labels:")
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")

    print("\nYear sources:")
    for source, count in sorted(year_source_counts.items()):
        print(f"  {source}: {count}")

    print(f"\nTop {args.top} ranked papers:")
    for index, paper in enumerate(papers[: args.top], start=1):
        title = paper.get("title", "Untitled")
        label = paper.get("relevance_label", "?")
        score = paper.get("rank_score", paper.get("relevance_score", 0))
        query_score = paper.get("query_score", 0)
        year = paper.get("year", "Not Reported")
        year_source = paper.get("year_source", "?")
        query_matches = ", ".join(paper.get("query_matches") or []) or "(none)"
        synonym_matches = ", ".join(paper.get("technology_synonym_matches") or []) or "(none)"
        print(f"  {index}. [{label}] rank={score} query={query_score} {year} ({year_source}) {title}")
        print(f"      query_matches: {query_matches}")
        print(f"      technology_synonym_matches: {synonym_matches}")

    negative_papers = [p for p in papers if p.get("negative_topic_matches")]
    print(f"\nPapers with negative topic matches: {len(negative_papers)}")
    for paper in negative_papers[:10]:
        negatives = ", ".join(paper.get("negative_topic_matches") or [])
        print(f"  - {paper.get('title', 'Untitled')}: {negatives}")

    inferred_or_missing = [
        p
        for p in papers
        if p.get("year_source") in {"doi_inferred", "not_reported"}
        or p.get("year") in {None, "", "Not Reported"}
    ]
    print(f"\nPapers with inferred or missing year: {len(inferred_or_missing)}")
    for paper in inferred_or_missing[:10]:
        print(
            f"  - {paper.get('year', 'Not Reported')} ({paper.get('year_source', '?')}): "
            f"{paper.get('title', 'Untitled')}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
