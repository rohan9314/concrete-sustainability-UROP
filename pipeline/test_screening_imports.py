"""Import and parsing checks for lightweight CCS abstract screening."""

from __future__ import annotations

import ast
import importlib
import importlib.abc
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.llm_utils import _parse_json_response

FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "backend.llm",
        "llm",
        "retrieval",
        "search",
        "tavily",
        "tiktoken",
        "openai_flex",
        "paper_records",
    }
)


def _import_roots_from_file(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_classifier_source_has_no_heavy_imports() -> None:
    classifier_path = REPO_ROOT / "pipeline" / "ccs_abstract_classifier.py"
    roots = _import_roots_from_file(classifier_path)
    blocked = roots & FORBIDDEN_IMPORT_ROOTS
    assert not blocked, f"Forbidden imports in ccs_abstract_classifier.py: {sorted(blocked)}"


def test_import_screening_modules_without_tavily() -> None:
    blocked_modules = {
        name
        for name in list(sys.modules)
        if name == "tavily" or name.startswith("tavily.")
    }
    for name in blocked_modules:
        sys.modules.pop(name, None)

    class TavilyBlocker(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):  # noqa: ANN001
            if fullname == "tavily" or fullname.startswith("tavily."):
                raise ModuleNotFoundError(f"No module named {fullname!r}")
            return None

    blocker = TavilyBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        for module_name in (
            "pipeline.ccs_abstract_classifier",
            "pipeline.run_ccs_abstract_screening",
        ):
            sys.modules.pop(module_name, None)
            importlib.import_module(module_name)
        assert "tavily" not in sys.modules
        assert "tiktoken" not in sys.modules
    finally:
        sys.meta_path.remove(blocker)


def test_parse_json_response_plain() -> None:
    data = _parse_json_response('{"is_relevant": true, "confidence": 0.8}')
    assert data["is_relevant"] is True
    assert data["confidence"] == 0.8


def test_parse_json_response_fenced() -> None:
    raw = """Here is the result:
```json
{"is_relevant": false, "relevant_subpaths": []}
```
"""
    data = _parse_json_response(raw)
    assert data["is_relevant"] is False
    assert data["relevant_subpaths"] == []


def test_parse_json_response_extra_text() -> None:
    raw = (
        "Classification complete.\n"
        '{"is_relevant": true, "relevant_subpaths": ["chemical_absorption"]}\n'
        "End of response."
    )
    data = _parse_json_response(raw)
    assert data["is_relevant"] is True
    assert data["relevant_subpaths"] == ["chemical_absorption"]


def main() -> int:
    tests = [
        test_classifier_source_has_no_heavy_imports,
        test_import_screening_modules_without_tavily,
        test_parse_json_response_plain,
        test_parse_json_response_fenced,
        test_parse_json_response_extra_text,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} screening import checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
