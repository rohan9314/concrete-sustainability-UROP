"""Shard planning helpers for distributed corpus processing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusShard:
    index: int
    start: int
    end: int

    @property
    def label(self) -> str:
        return f"{self.start}_{self.end}"


def plan_corpus_shards(total_records: int, shard_size: int) -> list[CorpusShard]:
    """Split a corpus into contiguous index ranges for array jobs."""
    if total_records <= 0:
        return []
    if shard_size <= 0:
        raise ValueError("shard_size must be positive")

    shards: list[CorpusShard] = []
    start = 0
    index = 0
    while start < total_records:
        end = min(start + shard_size, total_records)
        shards.append(CorpusShard(index=index, start=start, end=end))
        start = end
        index += 1
    return shards


def shard_for_array_task(shards: list[CorpusShard], task_id: int) -> CorpusShard:
    """Select a shard by SLURM_ARRAY_TASK_ID-style index."""
    if task_id < 0 or task_id >= len(shards):
        raise IndexError(f"task_id {task_id} out of range for {len(shards)} shards")
    return shards[task_id]
