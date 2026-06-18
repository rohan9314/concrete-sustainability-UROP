#!/usr/bin/env python3
"""
Research agent CLI for cement and concrete decarbonization technologies.

Usage:
    python main.py "calcium looping"
    python main.py "calcium looping" --questions carbon_capture
"""

import argparse
import json
import re
import sys
from pathlib import Path

from research_pipeline import ResearchPipelineError, run_research_pipeline
from questions import DEFAULT_QUESTION_SET, list_question_sets

OUTPUT_DIR = Path(__file__).parent / "outputs"


def _technology_to_filename(technology_name: str) -> str:
    slug = technology_name.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug or "technology"


def _save_output(result: dict, technology_name: str, question_set: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tech_slug = _technology_to_filename(technology_name)
    set_slug = _technology_to_filename(question_set)
    output_path = OUTPUT_DIR / f"{tech_slug}_{set_slug}.json"
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return output_path


def _build_parser() -> argparse.ArgumentParser:
    available = list_question_sets()
    sets_help = ", ".join(available) if available else "none found"
    parser = argparse.ArgumentParser(
        description="Research agent for cement and concrete decarbonization technologies."
    )
    parser.add_argument("technology", help='Technology to research (e.g. "calcium looping")')
    parser.add_argument(
        "--questions",
        "-q",
        default=DEFAULT_QUESTION_SET,
        metavar="SET",
        help=f"Question set to use. Default: {DEFAULT_QUESTION_SET}. Available: {sets_help}",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    def on_progress(step: str, message: str) -> None:
        print(message)

    try:
        result = run_research_pipeline(
            args.technology,
            args.questions,
            progress_callback=on_progress,
        )
    except ResearchPipelineError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        return 1

    output_path = _save_output(result, args.technology, args.questions)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("-" * 50)
    print(f"Saved to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
