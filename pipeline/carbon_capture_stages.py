"""Cluster-oriented stages for the carbon capture pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from pipeline.carbon_capture_config import CarbonCaptureMethodology, get_methodology
from pipeline.carbon_capture_extraction import (
    CarbonCaptureRow,
    extract_literature_papers_parallel,
    extract_web_sources_parallel,
)
from pipeline.carbon_capture_io import (
    merge_extractions,
    merge_ranked_papers,
    merge_screening_shards,
    write_extraction_shard,
    write_ranked_final,
    write_ranked_shard,
)
from pipeline.carbon_capture_retrieval import retrieve_methodology_papers
from pipeline.carbon_capture_schema import ValidationStats
from pipeline.carbon_capture_web import discover_web_sources
from pipeline.corpus_loader import load_paper_records

logger = logging.getLogger(__name__)


def retrieve_methodology_shard(
    methodology: CarbonCaptureMethodology,
    *,
    start: int,
    end: int,
    screening_results: str | Path | None,
    input_path: str | Path | None,
    output_path: str | Path,
) -> Path:
    """
    Rank all methodology-relevant papers in a corpus shard.

  Does not apply global top_n — shard workers emit every candidate so a merge
  step can choose the corpus-wide top papers.
    """
    ranked = retrieve_methodology_papers(
        methodology,
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
        methodology_slug=methodology.slug,
        shard_start=start,
        shard_end=end,
    )


def merge_methodology_ranked_shards(
    methodology_slug: str,
    shard_paths: list[str | Path],
    *,
    top_n: int,
    output_path: str | Path,
) -> Path:
    methodology = get_methodology(methodology_slug)
    merged = merge_ranked_papers(shard_paths, top_n=top_n)
    logger.info(
        "Merged %s ranked shard files into %s papers (top_n=%s) for %s",
        len(shard_paths),
        len(merged),
        top_n,
        methodology.slug,
    )
    return write_ranked_final(merged, output_path, methodology_slug=methodology.slug)


def extract_methodology_ranked_list(
    methodology: CarbonCaptureMethodology,
    ranked_paths: list[str | Path],
    *,
    output_path: str | Path,
    batch_start: int = 0,
    batch_end: int | None = None,
    concurrency: int | None = None,
    input_path: str | Path | None = None,
) -> Path:
    """Extract a slice of globally ranked papers for one methodology."""
    import logging

    from pipeline.carbon_capture_io import read_ranked_final
    from pipeline.load_corpus import load_corpus

    logger = logging.getLogger(__name__)

    papers: list = []
    for path in ranked_paths:
        loaded = read_ranked_final(path)
        logger.info("Loaded %s ranked papers from %s", len(loaded), path)
        papers.extend(loaded)
    total_ranked = len(papers)
    if total_ranked == 0:
        paths = ", ".join(str(path) for path in ranked_paths)
        raise ValueError(
            f"No ranked papers found in {paths}. "
            "Check OUTPUT_DIR, merge-rank output, and that files contain type=ranked_paper rows.",
        )
    if batch_end is not None:
        papers = papers[batch_start:batch_end]
    elif batch_start:
        papers = papers[batch_start:]
    logger.info(
        "Extract batch %s-%s: %s papers (from %s total ranked)",
        batch_start,
        batch_end if batch_end is not None else total_ranked,
        len(papers),
        total_ranked,
    )

    paper_ids = {paper.paper_id for paper in papers}
    if paper_ids:
        enriched_by_id = {
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
                    "text": enriched_by_id[paper.paper_id].text,
                    "abstract": enriched_by_id[paper.paper_id].abstract or paper.abstract,
                },
            )
            if paper.paper_id in enriched_by_id
            else paper
            for paper in papers
        ]

    results = extract_literature_papers_parallel(
        papers,
        methodology,
        concurrency=concurrency,
    )
    return write_extraction_shard(
        results,
        output_path,
        methodology_slug=methodology.slug,
        batch_start=batch_start,
        batch_end=batch_end if batch_end is not None else batch_start + len(results),
        source_origin="literature",
    )


def merge_methodology_extractions(
    shard_paths: list[str | Path],
    *,
    output_path: str | Path,
) -> Path:
    merged = merge_extractions(shard_paths)
    methodology_slug = "unknown"
    if merged:
        methodology_slug = merged[0].methodology_slug
    return write_extraction_shard(
        merged,
        output_path,
        methodology_slug=methodology_slug,
        batch_start=0,
        batch_end=len(merged),
    )


def extract_web_for_methodology(
    methodology: CarbonCaptureMethodology,
    *,
    literature_rows: list[CarbonCaptureRow],
    output_path: str | Path,
    max_results_per_query: int = 5,
    max_total_sources: int | None = None,
    concurrency: int | None = None,
    stats: ValidationStats | None = None,
) -> Path:
    """
    Discover and extract web sources for one methodology.

    Uses technology-level Tavily queries plus company/project follow-ups seeded
    from literature extraction rows.
    """
    sources = discover_web_sources(
        methodology,
        seed_rows=literature_rows,
        max_results_per_query=max_results_per_query,
        max_total_sources=max_total_sources,
    )
    rows: list[CarbonCaptureRow] = []
    if sources:
        rows = extract_web_sources_parallel(
            sources,
            methodology,
            concurrency=concurrency,
            stats=stats,
        )
    logger.info(
        "Web extraction for %s: %s sources -> %s rows",
        methodology.slug,
        len(sources),
        len(rows),
    )
    return write_extraction_shard(
        rows,
        output_path,
        methodology_slug=methodology.slug,
        batch_start=0,
        batch_end=len(rows),
        source_origin="web",
    )


def merge_screening_outputs(
    shard_paths: list[str | Path],
    output_path: str | Path,
) -> Path:
    return merge_screening_shards(shard_paths, output_path)


def corpus_record_count(input_path: str | Path | None = None) -> int:
    return len(load_paper_records(input_path))
