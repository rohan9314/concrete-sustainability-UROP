"""Load evaluation question sets from JSON files."""

import json
import re
from pathlib import Path

QUESTIONS_DIR = Path(__file__).parent / "questions"
DEFAULT_QUESTION_SET = "evaluation_questions"

_DEFAULT_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "evaluation_questions": {
        "label": "Decarbonization Technology Evaluation Framework",
        "description": "Comprehensive evaluation across technology overview, supply chain, performance, environmental, energy, economic, deployment, and evidence dimensions.",
    },
    "general_decarbonization": {
        "label": "Decarbonization Technology Evaluation Framework",
        "description": "Comprehensive evaluation across technology overview, supply chain, performance, environmental, energy, economic, deployment, and evidence dimensions.",
    },
    "carbon_capture": {
        "label": "Carbon Capture",
        "description": "Capture mechanism, capture rate, CAPEX/OPEX, and integration with cement plants.",
    },
    "scm": {
        "label": "Supplementary Cementitious Materials (SCMs)",
        "description": "Material composition, clinker substitution rate, performance, and supply availability.",
    },
    "alternative_cement": {
        "label": "Alternative Cement",
        "description": "Novel chemistry, performance vs. OPC, standards compliance, and adoption barriers.",
    },
}


class QuestionSetNotFoundError(Exception):
    """Raised when a requested question set file does not exist."""


class InvalidQuestionSetError(Exception):
    """Raised when a question set file has invalid structure."""


def _resolve_question_path(question_set: str) -> Path:
    """Map a question set name or filename to its path under questions/."""
    name = question_set.strip()
    if not name:
        name = DEFAULT_QUESTION_SET
    if not name.endswith(".json"):
        name = f"{name}.json"
    return QUESTIONS_DIR / name


def _humanize_set_id(set_id: str) -> str:
    return re.sub(r"\s+", " ", set_id.replace("_", " ").strip()).title()


def _load_question_set_data(question_set: str = DEFAULT_QUESTION_SET) -> dict:
    path = _resolve_question_path(question_set)
    if not path.is_file():
        available = list_question_sets()
        hint = f" Available sets: {', '.join(available)}" if available else ""
        raise QuestionSetNotFoundError(
            f"Question set not found: {path.name}.{hint}"
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidQuestionSetError(
            f"Invalid JSON in {path.name}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise InvalidQuestionSetError(f"{path.name} must contain a JSON object.")

    return data


def list_question_sets() -> list[str]:
    """Return available question set names (without .json extension)."""
    if not QUESTIONS_DIR.is_dir():
        return []
    return sorted(path.stem for path in QUESTIONS_DIR.glob("*.json"))


def load_questions(question_set: str = DEFAULT_QUESTION_SET) -> list[str]:
    """
    Load questions from a JSON file in questions/.

    The file must contain a top-level "questions" array of non-empty strings.
    Researchers can add, remove, or edit questions by editing the JSON only.
    """
    data = _load_question_set_data(question_set)
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise InvalidQuestionSetError(
            f"{_resolve_question_path(question_set).name} must contain a non-empty 'questions' array."
        )

    cleaned: list[str] = []
    for i, question in enumerate(questions, start=1):
        if not isinstance(question, str) or not question.strip():
            raise InvalidQuestionSetError(
                f"{_resolve_question_path(question_set).name}: question at index {i} must be a non-empty string."
            )
        cleaned.append(question.strip())

    return cleaned


def question_set_name(question_set: str = DEFAULT_QUESTION_SET) -> str:
    """Return the normalized question set name (filename stem)."""
    name = question_set.strip() or DEFAULT_QUESTION_SET
    if name.endswith(".json"):
        name = name[:-5]
    return name


def get_question_set_info(question_set: str) -> dict:
    """Return id, label, description, and question_count for API responses."""
    set_id = question_set_name(question_set)
    data = _load_question_set_data(set_id)
    questions = load_questions(set_id)
    defaults = _DEFAULT_DESCRIPTIONS.get(set_id, {})

    label = data.get("label") or defaults.get("label") or _humanize_set_id(set_id)
    description = data.get("description") or defaults.get("description") or (
        f"Evaluation questions for {label.lower()} research."
    )

    return {
        "id": set_id,
        "label": str(label),
        "description": str(description),
        "question_count": len(questions),
    }


def list_question_sets_info() -> list[dict]:
    """Return metadata for all available question sets."""
    return [get_question_set_info(set_id) for set_id in list_question_sets()]
