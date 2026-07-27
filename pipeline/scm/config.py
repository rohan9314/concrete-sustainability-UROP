"""SCM pipeline configuration, output roots, and promotion thresholds."""

from __future__ import annotations

import os
from pathlib import Path

from pipeline.config import get_output_dir
from pipeline.scm.seed_categories import OUTPUT_DIR_NAME

# Promotion defaults for discovery → dedicated pipeline recommendations.
MIN_STRONGLY_RELEVANT_RECORDS = 20
MIN_UNIQUE_SOURCES = 10
MIN_INDEPENDENT_ORGANIZATIONS = 5
MIN_LITERATURE_SOURCES = 5

DEFAULT_TEST_OUTPUT_DIR = Path("test") / "scm"
ALIAS_OVERRIDES_RELATIVE = Path("config") / "scm" / "scm_material_alias_overrides.json"
# Backward-compatible location if the new path is absent.
ALIAS_OVERRIDES_LEGACY = Path("config") / "scm_material_alias_overrides.json"
CANDIDATE_CONFIG_DIR = Path("config") / "scm_candidates"

CATEGORY_ID = "scm"
CATEGORY_LABEL = "Supplementary Cementitious Materials"
CARBON_CAPTURE_OUTPUT_DIR_NAME = "carbon_capture"


def get_promotion_thresholds() -> dict[str, int]:
    """Configurable promotion thresholds (env overrides defaults)."""

    def _int(name: str, default: int) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            return max(1, int(raw))
        except ValueError:
            return default

    return {
        "min_strongly_relevant_records": _int(
            "SCM_MIN_STRONGLY_RELEVANT_RECORDS",
            MIN_STRONGLY_RELEVANT_RECORDS,
        ),
        "min_unique_sources": _int("SCM_MIN_UNIQUE_SOURCES", MIN_UNIQUE_SOURCES),
        "min_independent_organizations": _int(
            "SCM_MIN_INDEPENDENT_ORGANIZATIONS",
            MIN_INDEPENDENT_ORGANIZATIONS,
        ),
        "min_literature_sources": _int(
            "SCM_MIN_LITERATURE_SOURCES",
            MIN_LITERATURE_SOURCES,
        ),
    }


def carbon_capture_output_root() -> Path:
    """Resolve the carbon-capture output root (for collision checks only)."""
    raw = (
        os.getenv("CARBON_CAPTURE_OUTPUT_ROOT", "").strip()
        or os.getenv("CCS_OUTPUT_ROOT", "").strip()
    )
    if raw:
        path = Path(raw).expanduser()
        return path.resolve() if path.is_absolute() else (get_output_dir() / path).resolve()
    return (get_output_dir() / CARBON_CAPTURE_OUTPUT_DIR_NAME).resolve()


def assert_scm_output_isolated(path: Path) -> Path:
    """Reject SCM roots that collide with the carbon-capture output directory."""
    resolved = path.resolve()
    cc_root = carbon_capture_output_root()
    if resolved == cc_root:
        raise ValueError(
            "SCM and carbon-capture output directories must be different. "
            f"Both resolve to {resolved}. Set SCM_OUTPUT_ROOT separately.",
        )
    # Also reject writing directly into a carbon_capture tree.
    try:
        resolved.relative_to(cc_root)
        raise ValueError(
            f"SCM output root {resolved} is inside carbon-capture root {cc_root}. "
            "Choose a separate SCM_OUTPUT_ROOT.",
        )
    except ValueError as exc:
        if "inside carbon-capture" in str(exc) or "must be different" in str(exc):
            raise
        # relative_to failed → path is not inside cc_root (good)
    if resolved.name == CARBON_CAPTURE_OUTPUT_DIR_NAME:
        raise ValueError(
            "SCM pipeline refused to write into a directory named 'carbon_capture'.",
        )
    return resolved


def scm_output_root(raw: str = "", *, test_mode: bool = False) -> Path:
    """
    Resolve SCM output root.

    Priority:
      1. Explicit ``raw`` / CLI ``--out-dir``
      2. ``SCM_OUTPUT_ROOT`` environment variable
      3. Test default: ``$OUTPUT_DIR/test/scm``
      4. Production default: ``$OUTPUT_DIR/scm``

    Never depends on carbon-capture outputs or ``CARBON_CAPTURE_OUTPUT_ROOT``.
    """
    base = get_output_dir()
    if raw:
        path = Path(raw)
        if path.is_absolute():
            return assert_scm_output_isolated(path)
        raw_posix = path.as_posix()
        if raw_posix.startswith("outputs/"):
            path = Path(raw_posix[len("outputs/") :])
        return assert_scm_output_isolated(base / path)

    env = os.getenv("SCM_OUTPUT_ROOT", "").strip()
    if env and not test_mode:
        path = Path(env).expanduser()
        if path.is_absolute():
            return assert_scm_output_isolated(path)
        return assert_scm_output_isolated(base / path)

    if test_mode:
        return assert_scm_output_isolated(base / DEFAULT_TEST_OUTPUT_DIR)
    return assert_scm_output_isolated(base / OUTPUT_DIR_NAME)


def alias_overrides_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    preferred = root / ALIAS_OVERRIDES_RELATIVE
    if preferred.is_file():
        return preferred
    return root / ALIAS_OVERRIDES_LEGACY


def candidate_config_dir(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[2]
    return root / CANDIDATE_CONFIG_DIR


def ensure_scm_layout(output_root: Path) -> dict[str, Path]:
    """Create SCM-only subdirectories (never creates carbon-capture paths)."""
    root = assert_scm_output_isolated(output_root)
    layout = {
        "root": root,
        "screening": root / "screening",
        "retrieval": root / "retrieval",
        "literature": root / "literature",
        "web": root / "web",
        "merged": root / "merged",
        "discovery": root / "discovery",
        "citations": root / "citations",
        "checkpoints": root / "checkpoints",
        "logs": root / "logs",
        "shards": root / "shards",
        "csv": root / "csv",
    }
    for path in layout.values():
        path.mkdir(parents=True, exist_ok=True)
    return layout


def path_is_under_scm_root(path: Path, scm_root: Path) -> bool:
    try:
        path.resolve().relative_to(scm_root.resolve())
        return True
    except ValueError:
        return False


def assert_input_under_scm_root(path: str | Path, scm_root: Path, *, label: str) -> Path:
    """Ensure screening/retrieval inputs belong to the SCM output tree."""
    resolved = Path(path).resolve()
    if not path_is_under_scm_root(resolved, scm_root):
        raise ValueError(
            f"{label} path {resolved} is outside SCM output root {scm_root.resolve()}. "
            "SCM commands must not read carbon-capture screening or retrieval files.",
        )
    return resolved
