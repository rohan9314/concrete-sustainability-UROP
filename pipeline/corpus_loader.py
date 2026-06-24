"""Load local pickle corpora without the backend retrieval stack."""

from __future__ import annotations

import logging
import pickle
import sys
import time
from pathlib import Path
from types import ModuleType

from pipeline.config import get_pickle_path

logger = logging.getLogger(__name__)

_cached_records: list[dict] | None = None
_cached_path: str | None = None


class PaperDatabaseLoadError(Exception):
    """Raised when the local paper database cannot be loaded."""


class _ObjectIdStub:
    """Minimal bson.objectid.ObjectId stand-in for unpickling corpus files."""

    def __setstate__(self, value: object) -> None:
        if isinstance(value, dict):
            self._id = value["_ObjectId__id"]
        else:
            self._id = value

    def __getstate__(self) -> object:
        return self._id


def _register_bson_stubs() -> None:
    """Register bson modules so pickle files with ObjectId values can load."""
    if "bson.objectid" in sys.modules:
        return

    bson_module = ModuleType("bson")
    objectid_module = ModuleType("bson.objectid")
    objectid_module.ObjectId = _ObjectIdStub
    bson_module.objectid = objectid_module
    sys.modules["bson"] = bson_module
    sys.modules["bson.objectid"] = objectid_module


def load_paper_records(path: str | Path | None = None) -> list[dict]:
    """Load cement/concrete paper records from a local pickle file."""
    global _cached_records, _cached_path

    pickle_path = Path(path) if path else get_pickle_path()
    resolved = pickle_path.expanduser().resolve()
    resolved_str = str(resolved)

    if _cached_records is not None and _cached_path == resolved_str:
        return _cached_records

    if not resolved.is_file():
        raise PaperDatabaseLoadError(
            f"Local paper database not found: {resolved}. "
            "Set PICKLE_PATH or PAPER_RECORDS_PATH to a readable pickle file."
        )

    _register_bson_stubs()
    try:
        started = time.perf_counter()
        with resolved.open("rb") as handle:
            raw = pickle.load(handle)
        logger.info(
            "pickle_load: loaded %s records from %s (%.2fs)",
            len(raw) if isinstance(raw, (list, dict)) else "?",
            resolved,
            time.perf_counter() - started,
        )
    except Exception as exc:
        raise PaperDatabaseLoadError(
            f"Failed to load local paper database at {resolved}."
        ) from exc

    if isinstance(raw, list):
        records = [item for item in raw if isinstance(item, dict)]
    elif isinstance(raw, dict):
        records = [value for value in raw.values() if isinstance(value, dict)]
    else:
        records = []

    if not records:
        raise PaperDatabaseLoadError(
            "Local paper database loaded but contained no usable records."
        )

    _cached_records = records
    _cached_path = resolved_str
    return records


def load_paper_records_slice(
    *,
    path: str | Path | None = None,
    start: int = 0,
    end: int | None = None,
) -> tuple[list[dict], int]:
    """Load a slice of raw pickle records. Returns (records, slice_end)."""
    all_records = load_paper_records(path)
    slice_end = len(all_records) if end is None else end
    return all_records[start:slice_end], slice_end
