"""Shared helpers for Concrete Decarbonization offline tests.

Not collected as tests. No live OpenAI/Tavily/Engaging.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from pipeline.cementitious.schema import RECORD_FIELDS
from pipeline.cementitious.web_config import WebLimits


REPRESENTATIVE_PATHS: tuple[tuple[str, ...], ...] = (
    (
        "Concrete Decarbonization",
        "Cementitious Materials",
        "Conventional and Blended Cements",
        "Ordinary Portland Cement",
        "OPC",
    ),
    (
        "Concrete Decarbonization",
        "Cementitious Materials",
        "Cement-Plant Carbon Capture",
        "Chemical Absorption",
        "Amine Absorption",
    ),
    (
        "Concrete Decarbonization",
        "Aggregate Procurement",
        "Recycled Concrete Aggregates",
        "Treated RCA",
        "Carbonated RCA",
    ),
    (
        "Concrete Decarbonization",
        "Concrete Design",
        "Design for Durability",
        "Self-Healing Concrete",
        "Bacterial Self-Healing Concrete",
    ),
    (
        "Concrete Decarbonization",
        "Policy",
        "Green Public Procurement",
        "Embodied-Carbon Procurement Limits",
        "Buy Clean Programs",
    ),
    (
        "Concrete Decarbonization",
        "Structural and Construction Design",
        "Efficient Concrete Use",
        "Topology Optimization",
        "Topology-Optimized Floors",
    ),
    (
        "Concrete Decarbonization",
        "Operation",
        "Optimal Overdesign",
        "Mix Overdesign Reduction",
        "Reduced Strength Overdesign",
    ),
    (
        "Concrete Decarbonization",
        "End-of-Life",
        "End-of-Life Carbonation",
        "Enhanced Concrete Carbonation",
        "Crushing-Enhanced Carbonation",
    ),
)

SYNTHETIC_LITERATURE_CASES: tuple[dict[str, str], ...] = (
    {
        "title": "Carbonated recycled concrete aggregate as treated RCA",
        "abstract": (
            "Treated recycled concrete aggregates were carbonated to produce carbonated RCA "
            "for aggregate procurement in structural concrete."
        ),
        "level_1": "Aggregate Procurement",
        "level_4": "Carbonated RCA",
    },
    {
        "title": "Bacterial self-healing concrete for durability design",
        "abstract": (
            "A bacterial self-healing concrete mix was developed under design for durability "
            "using self-healing concrete techniques."
        ),
        "level_1": "Concrete Design",
        "level_4": "Bacterial Self-Healing Concrete",
    },
    {
        "title": "Topology-optimized concrete floors reduce material use",
        "abstract": (
            "Topology optimization of topology-optimized floors enables efficient concrete use "
            "in structural and construction design."
        ),
        "level_1": "Structural and Construction Design",
        "level_4": "Topology-Optimized Floors",
    },
    {
        "title": "Reducing mix strength overdesign in ready-mix operations",
        "abstract": (
            "Optimal overdesign practices reduced mix overdesign. Reduced strength overdesign "
            "cut cement use during concrete plant operation."
        ),
        "level_1": "Operation",
        "level_4": "Reduced Strength Overdesign",
    },
    {
        "title": "Buy Clean programs and embodied-carbon procurement limits",
        "abstract": (
            "Green public procurement adopted Buy Clean programs with embodied-carbon "
            "procurement limits for cement and concrete."
        ),
        "level_1": "Policy",
        "level_4": "Buy Clean Programs",
    },
    {
        "title": "Crushing-enhanced carbonation of demolished concrete",
        "abstract": (
            "End-of-life carbonation was enhanced by crushing-enhanced carbonation of "
            "demolished concrete to increase enhanced concrete carbonation."
        ),
        "level_1": "End-of-Life",
        "level_4": "Crushing-Enhanced Carbonation",
    },
    {
        "title": "Amine absorption carbon capture at a cement plant",
        "abstract": (
            "Cement-plant carbon capture used chemical absorption via amine absorption "
            "on kiln flue gas."
        ),
        "level_1": "Cementitious Materials",
        "level_4": "Amine Absorption",
    },
)

OLD_LEAF_EXAMPLES: tuple[str, ...] = (
    "chemical_absorption",
    "cryogenic_carbon_capture",
    "oxy_fuel_combustion",
    "membrane_separation",
    "calcium_looping",
    "direct_separation",
    "slag_cement",
    "coal_ash",
    "silica_fume",
    "natural_pozzolans",
    "biomass_ashes",
    "mine_tailings",
    "alkali_activated_cements",
    "calcium_silicate_cements",
    "engineered_ultrafine_fillers",
    "carbonate_fillers",
)


def launch_env(tmp: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    tmp.mkdir(parents=True, exist_ok=True)
    pkl = tmp / "corpus.pkl"
    if not pkl.is_file():
        with pkl.open("wb") as handle:
            pickle.dump([paper_record(0)], handle)
    env = {
        "OPENAI_API_KEY": "sk-test-not-real",
        "TAVILY_API_KEY": "tvly-test-not-real",
        "PICKLE_PATH": str(pkl),
        "RESULTS_ROOT": str(tmp / "results"),
    }
    if extra:
        env.update(extra)
    return env


def paper_record(i: int, **overrides: Any) -> dict[str, Any]:
    row = {
        "title": f"Rice husk ash cement replacement study {i}",
        "abstract": (
            f"Rice husk ash was used as a supplementary cementitious material "
            f"in concrete. Trial {i}."
        ),
        "doi": f"10.1000/test.{i}",
        "year": 2020 + (i % 5),
        "url": f"https://journals.example/{i}",
    }
    row.update(overrides)
    return row


def write_pickle(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(records, handle)
    return path


def canonical_record(**fields: Any) -> dict[str, str]:
    rec = {k: "" for k in RECORD_FIELDS}
    rec.update(
        {
            "record_id": fields.get("record_id", "r1"),
            "taxonomy_level_0": fields.get("taxonomy_level_0", "Concrete Decarbonization"),
            "taxonomy_level_1": fields.get("taxonomy_level_1", "Cementitious Materials"),
            "taxonomy_level_2": fields.get("taxonomy_level_2", "Cement-Plant Carbon Capture"),
            "taxonomy_level_3": fields.get("taxonomy_level_3", "Chemical Absorption"),
            "taxonomy_level_4": fields.get("taxonomy_level_4", "Amine Absorption"),
            "source_id": fields.get("source_id", "test:1"),
            "citation": fields.get("citation", "doi:test"),
            "evidence_text": fields.get(
                "evidence_text", "synthetic evidence for canonical workflow tests."
            ),
            "extraction_confidence": fields.get("extraction_confidence", "High"),
            "taxonomy_confidence": fields.get("taxonomy_confidence", "High"),
            "classification_basis": fields.get("classification_basis", "Explicit"),
            "evidence_origin": fields.get("evidence_origin", "Literature"),
            "source_type": fields.get("source_type", "Academic Literature"),
        }
    )
    rec.update({k: str(v) if v is not None else "" for k, v in fields.items()})
    return rec


def web_limits(**overrides: Any) -> WebLimits:
    payload = dict(
        queries_per_subcategory=1,
        queries_per_sub_subcategory=2,
        results_per_query=3,
        max_urls_per_branch=50,
        max_total_urls=100,
        max_total_queries=0,
        search_shard_size=10,
        extract_shard_size=10,
        concurrency=2,
        request_timeout=5,
        max_retries=1,
        page_max_chars=5000,
        rate_limit_sleep_s=0.0,
    )
    payload.update(overrides)
    return WebLimits(**payload)


class FakeTavilyClient:
    """Deterministic Tavily stand-in. Records query texts; never touches the network."""

    calls: list[str] = []

    def __init__(self, results: list[dict[str, Any]] | None = None, *, fail_times: int = 0):
        self._results = results
        self._fail_times = fail_times
        self._failures = 0

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        FakeTavilyClient.calls.append(query)
        if self._failures < self._fail_times:
            self._failures += 1
            raise RuntimeError("simulated tavily failure")
        if self._results is not None:
            return {"results": self._results}
        n = len(FakeTavilyClient.calls)
        return {
            "results": [
                {
                    "title": f"Cement plant amine capture project {n}",
                    "url": f"https://example.com/projects/{n}?utm_source=x#frag",
                    "content": "Pilot cement plant carbon capture using amine solvent.",
                    "raw_content": "Full page: commercial demonstration, 400 kt CO2/year.",
                    "score": 0.9,
                },
                {
                    "title": f"Mirror page {n}",
                    "url": f"https://www.example.com/projects/{n}",
                    "content": "Same page mirrored.",
                    "raw_content": "",
                    "score": 0.5,
                },
            ][: int(kwargs.get("max_results") or 10)]
        }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def record_for_path(labels: tuple[str, ...], *, record_id: str, **fields: Any) -> dict[str, str]:
    payload = {
        "record_id": record_id,
        "taxonomy_level_0": labels[0] if len(labels) > 0 else "Concrete Decarbonization",
        "taxonomy_level_1": labels[1] if len(labels) > 1 else "N.A.",
        "taxonomy_level_2": labels[2] if len(labels) > 2 else "N.A.",
        "taxonomy_level_3": labels[3] if len(labels) > 3 else "N.A.",
        "taxonomy_level_4": labels[4] if len(labels) > 4 else "N.A.",
    }
    payload.update(fields)
    return canonical_record(**payload)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
