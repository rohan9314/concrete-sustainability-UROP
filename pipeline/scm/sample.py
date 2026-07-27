"""Reproducible SCM corpus sampling for local validation runs."""

from __future__ import annotations

import json
import pickle
import random
from datetime import datetime, timezone
from pathlib import Path

from pipeline.corpus_loader import load_paper_records, resolve_pickle_path
from pipeline.record_utils import record_dedupe_key


def sample_paper_records(
    *,
    sample_size: int = 100,
    random_seed: int = 42,
    input_path: str | Path | None = None,
) -> tuple[list[dict], list[str], dict]:
    """
    Sample ``sample_size`` records reproducibly from the corpus.

    Loads the full pickle once (required to sample across the corpus), then
    returns the sampled records, paper ids, and manifest metadata.
    """
    corpus_path = resolve_pickle_path(input_path, announce=True)
    records = load_paper_records(corpus_path)
    total = len(records)
    if total < sample_size:
        raise ValueError(
            f"Corpus has only {total} records; cannot sample {sample_size}.",
        )

    rng = random.Random(random_seed)
    indices = sorted(rng.sample(range(total), sample_size))
    sampled = [records[i] for i in indices]
    paper_ids: list[str] = []
    for offset, record in enumerate(sampled):
        paper_id = record_dedupe_key(record) or f"paper:{indices[offset]}"
        paper_ids.append(paper_id)

    meta = {
        "sample_size": sample_size,
        "sampling_method": "random.sample over full corpus indices",
        "random_seed": random_seed,
        "paper_ids": paper_ids,
        "source_corpus_path": str(corpus_path),
        "source_corpus_record_count": total,
        "sampled_indices": indices,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Full corpus pickle is loaded once to draw a reproducible sample; "
            "downstream stages use the 100-record sample pickle only."
        ),
    }
    return sampled, paper_ids, meta


def write_sample_artifacts(
    *,
    output_dir: Path,
    sample_size: int = 100,
    random_seed: int = 42,
    input_path: str | Path | None = None,
) -> tuple[Path, Path]:
    """Write sample pickle + JSON manifest under output_dir/manifests/."""
    sampled, _paper_ids, meta = sample_paper_records(
        sample_size=sample_size,
        random_seed=random_seed,
        input_path=input_path,
    )
    manifests = output_dir / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    pickle_path = manifests / f"paper_sample_{sample_size}.pkl"
    manifest_path = manifests / f"paper_sample_{sample_size}.json"
    with pickle_path.open("wb") as handle:
        pickle.dump(sampled, handle, protocol=pickle.HIGHEST_PROTOCOL)
    meta["sample_pickle_path"] = str(pickle_path)
    manifest_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return pickle_path, manifest_path
