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


def _unpickle_records(handle) -> object:
    """
    Unpickle corpus bytes, tolerating older pickle string encodings.

    Some corpus files were written in environments that store 8-bit strings;
    default utf-8 decoding then fails with UnicodeDecodeError.
    """
    errors: list[str] = []
    for encoding in (None, "latin-1", "bytes"):
        handle.seek(0)
        try:
            if encoding is None:
                return pickle.load(handle)
            return pickle.load(handle, encoding=encoding)
        except Exception as exc:
            errors.append(f"encoding={encoding!r}: {type(exc).__name__}: {exc}")
    raise PaperDatabaseLoadError(
        "Unable to unpickle corpus with default/latin-1/bytes encodings.\n"
        + "\n".join(errors)
    )


def _resolve_raw_path(path: str | Path | None = None) -> tuple[Path, str]:
    if path:
        return Path(path).expanduser().resolve(), f"explicit path ({path})"
    return get_pickle_path(), "PICKLE_PATH / PAPER_RECORDS_PATH"


def resolve_pickle_path(path: str | Path | None = None, *, announce: bool = True) -> Path:
    """Resolve the effective pickle path (env var or explicit path)."""
    resolved, source = _resolve_raw_path(path)
    if announce:
        logger.info("Resolved paper corpus path: %s (from %s)", resolved, source)
        print(f"Resolved paper corpus path: {resolved}", flush=True)
        print(f"  source: {source}", flush=True)

    if not resolved.exists():
        raise PaperDatabaseLoadError(
            f"Local paper database not found: {resolved}\n"
            "Set PICKLE_PATH to an existing pickle file, for example:\n"
            "  export PICKLE_PATH=/absolute/path/to/filtered_records_rohan.pkl\n"
            "Do not assume the pickle lives inside the git repository."
        )
    if not resolved.is_file():
        raise PaperDatabaseLoadError(
            f"PICKLE_PATH points to a non-file path: {resolved}"
        )
    return resolved


def validate_pickle_corpus(path: str | Path | None = None) -> tuple[Path, int]:
    """
    Validate that the corpus pickle exists and can be loaded.

    Returns (resolved_path, record_count). Prints a short status line.
    """
    resolved = resolve_pickle_path(path, announce=True)
    records = load_paper_records(resolved)
    print(
        f"Validated paper corpus: {len(records)} records at {resolved}",
        flush=True,
    )
    return resolved, len(records)


def load_paper_records(path: str | Path | None = None) -> list[dict]:
    """Load cement/concrete paper records from a local pickle file."""
    global _cached_records, _cached_path

    resolved, source = _resolve_raw_path(path)
    resolved_str = str(resolved)

    if _cached_records is not None and _cached_path == resolved_str:
        return _cached_records

    # Announce only on first load of this path.
    logger.info("Resolved paper corpus path: %s (from %s)", resolved, source)
    print(f"Resolved paper corpus path: {resolved}", flush=True)
    print(f"  source: {source}", flush=True)

    if not resolved.exists():
        raise PaperDatabaseLoadError(
            f"Local paper database not found: {resolved}\n"
            "Set PICKLE_PATH to an existing pickle file, for example:\n"
            "  export PICKLE_PATH=/absolute/path/to/filtered_records_rohan.pkl\n"
            "Do not assume the pickle lives inside the git repository."
        )
    if not resolved.is_file():
        raise PaperDatabaseLoadError(
            f"PICKLE_PATH points to a non-file path: {resolved}"
        )

    _register_bson_stubs()
    try:
        started = time.perf_counter()
        with resolved.open("rb") as handle:
            raw = _unpickle_records(handle)
        logger.info(
            "pickle_load: loaded %s records from %s (%.2fs)",
            len(raw) if isinstance(raw, (list, dict)) else "?",
            resolved,
            time.perf_counter() - started,
        )
    except PaperDatabaseLoadError:
        raise
    except Exception as exc:
        raise PaperDatabaseLoadError(
            f"Failed to load local paper database at {resolved}.\n"
            f"Underlying error: {type(exc).__name__}: {exc}\n"
            "Check that PICKLE_PATH points to a complete, readable pickle "
            "(not a truncated copy or text/LFS pointer file)."
        ) from exc

    if isinstance(raw, list):
        records = [item for item in raw if isinstance(item, dict)]
    elif isinstance(raw, dict):
        records = [value for value in raw.values() if isinstance(value, dict)]
    else:
        records = []

    if not records:
        raise PaperDatabaseLoadError(
            f"Local paper database at {resolved} loaded but contained no usable dict records."
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
