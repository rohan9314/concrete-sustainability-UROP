"""Cluster-oriented stage helpers for the SCM pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.scm.export import write_jsonl_evidence
from pipeline.scm.extraction import (
    extract_discovery_papers_parallel,
    extract_literature_papers_parallel,
    extract_web_sources_parallel,
)
from pipeline.scm.io import (
    merge_evidence_shards,
    merge_ranked_papers,
    merge_screening_shards,
    read_evidence_shard,
    read_ranked_shard,
    write_discovery_shard,
    write_evidence_shard,
    write_ranked_final,
    write_ranked_shard,
    write_screening_shard,
)
from pipeline.scm.retrieval import retrieve_discovery_papers, retrieve_seed_category_papers
from pipeline.scm.schema import ValidationStats
from pipeline.scm.screening import classify_records_parallel
from pipeline.scm.seed_categories import get_seed_category
from pipeline.scm.web import discover_web_sources

logger = logging.getLogger(__name__)


def screen_shard(
    *,
    start: int,
    end: int,
    input_path: str | Path | None,
    output_path: str | Path,
    keyword_only: bool = False,
) -> Path:
    from pipeline.load_corpus import load_paper_records_slice

    records, slice_end = load_paper_records_slice(
        path=input_path,
        start=start,
        end=end,
    )
    results = classify_records_parallel(
        records,
        start_index=start,
        keyword_only=keyword_only,
    )
    return write_screening_shard(
        results,
        output_path,
        shard_start=start,
        shard_end=slice_end,
    )


def retrieve_seed_shard(
    slug: str,
    *,
    start: int,
    end: int,
    screening_results: str | Path | None,
    input_path: str | Path | None,
    output_path: str | Path,
) -> Path:
    category = get_seed_category(slug)
    ranked = retrieve_seed_category_papers(
        category,
        start=start,
        end=end,
        top_n=0,
        screening_results=screening_results,
        input_path=input_path,
        include_full_text=False,
    )
    return write_ranked_shard(
        ranked,
        output_path,
        category_slug=slug,
        shard_start=start,
        shard_end=end,
    )


def merge_seed_ranked(
    slug: str,
    shard_paths: list[str | Path],
    *,
    top_n: int,
    output_path: str | Path,
) -> Path:
    merged = merge_ranked_papers(shard_paths, top_n=top_n)
    return write_ranked_final(merged, output_path, category_slug=slug)


def extract_seed_ranked(
    slug: str,
    ranked_paths: list[str | Path],
    *,
    output_path: str | Path,
    batch_start: int = 0,
    batch_end: int | None = None,
    input_path: str | Path | None = None,
) -> Path:
    from pipeline.load_corpus import load_corpus

    category = get_seed_category(slug)
    papers = []
    for path in ranked_paths:
        papers.extend(read_ranked_shard(path))
    if batch_end is not None:
        papers = papers[batch_start:batch_end]
    elif batch_start:
        papers = papers[batch_start:]

    paper_ids = {paper.paper_id for paper in papers}
    if paper_ids:
        enriched = {
            paper.paper_id: paper
            for paper in load_corpus(
                path=input_path,
                start=0,
                end=10**9,
                paper_ids=paper_ids,
                include_full_text=True,
            )
        }
        papers = [
            paper.model_copy(
                update={
                    "text": enriched[paper.paper_id].text,
                    "abstract": enriched[paper.paper_id].abstract or paper.abstract,
                },
            )
            if paper.paper_id in enriched
            else paper
            for paper in papers
        ]

    rows = extract_literature_papers_parallel(papers, category)
    return write_evidence_shard(
        rows,
        output_path,
        category_slug=slug,
        batch_start=batch_start,
        batch_end=batch_end if batch_end is not None else batch_start + len(rows),
        source_origin="literature",
    )


def merge_seed_extractions(
    slug: str,
    shard_paths: list[str | Path],
    *,
    output_path: str | Path,
) -> Path:
    merged = merge_evidence_shards(shard_paths)
    return write_evidence_shard(
        merged,
        output_path,
        category_slug=slug,
        batch_start=0,
        batch_end=len(merged),
    )


def extract_seed_web(
    slug: str,
    *,
    literature_rows_path: str | Path,
    output_path: str | Path,
    max_results_per_query: int = 5,
    max_total_sources: int | None = None,
) -> Path:
    category = get_seed_category(slug)
    literature_rows = read_evidence_shard(literature_rows_path)
    if not literature_rows:
        from pipeline.scm.export import read_jsonl_evidence

        literature_rows = read_jsonl_evidence(literature_rows_path)
    sources = discover_web_sources(
        category,
        seed_rows=literature_rows,
        max_results_per_query=max_results_per_query,
        max_total_sources=max_total_sources,
    )
    rows = extract_web_sources_parallel(sources, category) if sources else []
    write_jsonl_evidence(Path(output_path), rows)
    return write_evidence_shard(
        rows,
        output_path,
        category_slug=slug,
        batch_start=0,
        batch_end=len(rows),
        source_origin="web",
    )


def merge_screening(shard_paths: list[str | Path], output_path: str | Path) -> Path:
    return merge_screening_shards(shard_paths, output_path)


def retrieve_discovery_shard(
    *,
    start: int,
    end: int,
    screening_results: str | Path | None,
    input_path: str | Path | None,
    output_path: str | Path,
) -> Path:
    ranked = retrieve_discovery_papers(
        start=start,
        end=end,
        top_n=0,
        screening_results=screening_results,
        input_path=input_path,
        include_full_text=False,
    )
    return write_ranked_shard(
        ranked,
        output_path,
        category_slug="discovery",
        shard_start=start,
        shard_end=end,
    )


def extract_discovery_ranked(
    ranked_paths: list[str | Path],
    *,
    output_path: str | Path,
    batch_start: int = 0,
    batch_end: int | None = None,
    input_path: str | Path | None = None,
) -> Path:
    from pipeline.load_corpus import load_corpus

    papers = []
    for path in ranked_paths:
        papers.extend(read_ranked_shard(path))
    if batch_end is not None:
        papers = papers[batch_start:batch_end]
    elif batch_start:
        papers = papers[batch_start:]

    paper_ids = {paper.paper_id for paper in papers}
    if paper_ids:
        enriched = {
            paper.paper_id: paper
            for paper in load_corpus(
                path=input_path,
                start=0,
                end=10**9,
                paper_ids=paper_ids,
                include_full_text=True,
            )
        }
        papers = [
            paper.model_copy(
                update={
                    "text": enriched[paper.paper_id].text,
                    "abstract": enriched[paper.paper_id].abstract or paper.abstract,
                },
            )
            if paper.paper_id in enriched
            else paper
            for paper in papers
        ]

    rows = extract_discovery_papers_parallel(papers, stats=ValidationStats())
    return write_discovery_shard(rows, output_path)
