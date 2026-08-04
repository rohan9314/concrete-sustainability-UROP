"""Results-root and output-path resolution for Cementitious Materials runs."""

from __future__ import annotations

import logging
import os
import re
import warnings
from pathlib import Path

from pipeline.config import REPO_ROOT
from pipeline.cementitious import LEGACY_RESULTS_DIR_NAME, RESULTS_DIR_NAME

logger = logging.getLogger(__name__)

UNSAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._\- ]+")


class StaleResultsRootError(ValueError):
    """Raised when RESULTS_ROOT / output points at legacy ``730 results``."""


def _strip_trailing_seps(path: Path) -> Path:
    # Path does not keep trailing slash after resolve, but normalize string forms.
    text = str(path)
    while text.endswith(("/", "\\")) and len(text) > 1:
        text = text[:-1]
    return Path(text)


def is_results_dirname(name: str) -> bool:
    return name.rstrip("/\\") == RESULTS_DIR_NAME


def is_legacy_results_dirname(name: str) -> bool:
    return name.rstrip("/\\") == LEGACY_RESULTS_DIR_NAME


def path_contains_legacy_results(path: Path | str) -> bool:
    parts = Path(path).parts
    return LEGACY_RESULTS_DIR_NAME in parts


def warn_if_legacy_results_path(path: Path | str, *, raise_error: bool = True) -> None:
    """Detect stale ``730 results`` paths and warn / optionally refuse."""
    p = Path(path)
    if not path_contains_legacy_results(p):
        return
    msg = (
        f"Stale Cementitious Materials output path detected: {p}. "
        f"Outputs must use '{RESULTS_DIR_NAME}', not '{LEGACY_RESULTS_DIR_NAME}'. "
        "Legacy directories are preserved and are not written to. "
        "Use resolve_results_dir() / migrate-legacy-results to migrate explicitly."
    )
    logger.error(msg)
    warnings.warn(msg, UserWarning, stacklevel=2)
    if raise_error:
        raise StaleResultsRootError(msg)


def normalize_path_input(raw: str | Path) -> Path:
    """Expand user, resolve relative against cwd then repo, preserve spaces."""
    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        cwd_candidate = (Path.cwd() / path)
        # Prefer resolved absolute form; do not require existence for planning.
        path = cwd_candidate.resolve(strict=False)
    else:
        path = path.resolve(strict=False)
    return _strip_trailing_seps(path)


def get_results_root() -> Path:
    """
    Resolve RESULTS_ROOT env (parent or direct results dir).

    If unset, defaults to ``<repository_root>/results``.
    Does not append ``7-30 results``; callers should use :func:`resolve_results_dir`.
    """
    raw = os.getenv("RESULTS_ROOT", "").strip()
    if not raw:
        path = REPO_ROOT / "results"
    else:
        path = normalize_path_input(raw)
        warn_if_legacy_results_path(path, raise_error=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_results_dir(
    results_root: str | Path | None = None,
    *,
    allow_legacy: bool = False,
) -> Path:
    """
    Canonical resolver for the Cementitious Materials output directory.

    Accepts either:
      - a parent directory → ``<parent>/7-30 results``
      - a path already named ``7-30 results`` → unchanged (no nesting)

    Never creates ``7-30 results/7-30 results``.

    Refuses legacy ``730 results`` paths unless ``allow_legacy=True`` (migration only).
    """
    if results_root is None:
        raw = os.getenv("RESULTS_ROOT", "").strip()
        root = normalize_path_input(raw) if raw else (REPO_ROOT / "results")
    else:
        root = normalize_path_input(results_root)

    if path_contains_legacy_results(root):
        warn_if_legacy_results_path(root, raise_error=not allow_legacy)
        if allow_legacy:
            return root

    if is_results_dirname(root.name):
        out = root
    else:
        out = root / RESULTS_DIR_NAME

    # Guard against accidental double append after string concatenation bugs
    if out.name == RESULTS_DIR_NAME and out.parent.name == RESULTS_DIR_NAME:
        out = out.parent

    return out


def get_730_results_dir(results_root: Path | None = None) -> Path:
    """Compatibility alias → :func:`resolve_results_dir` (name retained for imports)."""
    return resolve_results_dir(results_root)


def get_results_dir(results_root: Path | None = None) -> Path:
    """Return the canonical ``7-30 results`` directory."""
    return resolve_results_dir(results_root)


def sanitize_slug(value: str) -> str:
    """Normalize a slug; reject path traversal and unsafe characters."""
    text = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    text = re.sub(r"_+", "_", text)
    if not text:
        raise ValueError("Empty slug")
    if ".." in text or "/" in text or "\\" in text:
        raise ValueError(f"Unsafe slug (path traversal): {value!r}")
    if UNSAFE_FILENAME_RE.search(text):
        raise ValueError(f"Unsafe characters in slug: {value!r}")
    return text


def safe_partition_filename(slug: str, *, suffix: str = ".csv") -> str:
    cleaned = sanitize_slug(slug)
    name = f"{cleaned}{suffix}"
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"Unsafe partition filename: {name!r}")
    return name


def ensure_730_layout(output_dir: Path) -> dict[str, Path]:
    """Compatibility alias for :func:`ensure_results_layout`."""
    return ensure_results_layout(output_dir)


def ensure_results_layout(output_dir: Path) -> dict[str, Path]:
    """Create the required ``7-30 results`` directory tree."""
    output_dir = Path(output_dir)
    warn_if_legacy_results_path(output_dir, raise_error=True)
    layout = {
        "root": output_dir,
        "all_records": output_dir / "all_records",
        "subcategories": output_dir / "subcategories",
        "sub_subcategories": output_dir / "sub_subcategories",
        "citations": output_dir / "citations",
        "citations_subcategories": output_dir / "citations" / "subcategories",
        "citations_sub_subcategories": output_dir / "citations" / "sub_subcategories",
        "pending_taxonomy_review": output_dir / "pending_taxonomy_review",
        "logs": output_dir / "logs",
        "checkpoints": output_dir / "checkpoints",
        "rejected_records": output_dir / "rejected_records",
        "metadata": output_dir / "metadata",
        "failed_llm": output_dir / "logs" / "failed_llm_responses",
        "screening_shards": output_dir / "metadata" / "screening_shards",
        "screen_markers": output_dir / "checkpoints" / "screen_shards",
        "extraction_shards": output_dir / "metadata" / "extraction_shards",
        "extract_markers": output_dir / "checkpoints" / "extraction_shards",
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout


def resolve_output_dir(explicit: str | Path | None = None) -> Path:
    """
    Resolve the run output directory.

    Priority:
    1. explicit CLI ``--output`` (normalized; no nested ``7-30 results``)
    2. ``resolve_results_dir()`` from RESULTS_ROOT
    """
    if explicit:
        return resolve_results_dir(explicit)
    return resolve_results_dir()


def migrate_legacy_results(
    *,
    results_root: str | Path | None = None,
    mode: str = "copy",
) -> dict[str, str]:
    """
    Optional explicit migration from legacy ``730 results`` → ``7-30 results``.

    Does not run automatically. ``mode`` is ``copy`` or ``move``.
    """
    import shutil

    root = normalize_path_input(results_root) if results_root else get_results_root()
    # If root itself is the legacy dir, parent is the results parent
    if is_legacy_results_dirname(root.name):
        parent = root.parent
        legacy = root
    else:
        parent = root
        legacy = parent / LEGACY_RESULTS_DIR_NAME
    dest = parent / RESULTS_DIR_NAME
    if not legacy.is_dir():
        raise FileNotFoundError(f"Legacy directory not found: {legacy}")
    if dest.exists():
        raise FileExistsError(f"Destination already exists: {dest}")
    if mode == "move":
        shutil.move(str(legacy), str(dest))
        action = "moved"
    elif mode == "copy":
        shutil.copytree(legacy, dest)
        action = "copied"
    else:
        raise ValueError("mode must be 'copy' or 'move'")
    return {
        "action": action,
        "source": str(legacy),
        "destination": str(dest),
    }
