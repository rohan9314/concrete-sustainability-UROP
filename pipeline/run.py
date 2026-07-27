#!/usr/bin/env python3
"""
Shared orchestration entry point with explicit category selection.

A category must be selected explicitly. Missing --category is an error —
never interpreted as permission to run every registered pipeline.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline.run")

KNOWN_CATEGORIES = ("scm", "carbon_capture")


def get_pipeline(category: str):
    """Lazy factory — only the selected category's runner is imported."""
    key = category.strip().lower().replace("-", "_")
    if key == "scm":
        from pipeline.scm import __main__ as scm_main

        return scm_main
    if key in {"carbon_capture", "ccs"}:
        from pipeline import run_carbon_capture

        return run_carbon_capture
    raise ValueError(
        f"Unknown category: {category!r}. Choose one of: {', '.join(KNOWN_CATEGORIES)}.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Explicit category-gated pipeline runner (never runs all categories).",
    )
    parser.add_argument(
        "--category",
        required=False,
        default="",
        help="Required. One of: scm, carbon_capture",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the selected category entry point "
        "(use -- before category-specific flags if needed)",
    )
    args = parser.parse_args(argv)

    if not args.category:
        parser.error(
            "A category must be selected explicitly.\n"
            f"Choose one of: {', '.join(KNOWN_CATEGORIES)}.\n"
            "Examples:\n"
            "  python -m pipeline.run --category scm run-all-seed-categories --test-mode\n"
            "  python -m pipeline.run --category carbon_capture -- --methodology amine_absorption --test-mode",
        )

    try:
        module = get_pipeline(args.category)
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

    forwarded = list(args.passthrough)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]

    logger.info("Dispatching to category=%s (other categories disabled)", args.category)

    if args.category.strip().lower().replace("-", "_") in {"carbon_capture", "ccs"}:
        # carbon-capture main() reads sys.argv; preserve its existing signature.
        old_argv = sys.argv
        try:
            sys.argv = [old_argv[0], *forwarded]
            return int(module.main())
        finally:
            sys.argv = old_argv

    return int(module.main(forwarded))


if __name__ == "__main__":
    raise SystemExit(main())
