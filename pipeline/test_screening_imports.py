"""Import and parsing checks for lightweight CCS abstract screening."""

from __future__ import annotations

import ast
import importlib
import importlib.abc
import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

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

SCREENING_MODULES = (
    "pipeline.ccs_abstract_classifier",
    "pipeline.run_ccs_abstract_screening",
    "pipeline.screening",
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
    # openai_client may be imported lazily inside call sites, not at module top level.
    source = classifier_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_openai_client = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "pipeline.openai_client":
            top_level_openai_client = True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pipeline.openai_client" or alias.name.startswith(
                    "pipeline.openai_client."
                ):
                    top_level_openai_client = True
    assert not top_level_openai_client, (
        "ccs_abstract_classifier.py must not import pipeline.openai_client at module top level"
    )


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
            # Also drop openai_client / openai so we observe fresh import side effects.
            for stale in list(sys.modules):
                if stale in {"openai", "tiktoken"} or stale.startswith(
                    ("openai.", "tiktoken.", "pipeline.openai_client")
                ):
                    sys.modules.pop(stale, None)
            importlib.import_module(module_name)
        assert "tavily" not in sys.modules
        assert "tiktoken" not in sys.modules
        assert "openai" not in sys.modules
    finally:
        sys.meta_path.remove(blocker)


def test_import_screening_modules_clean_subprocess() -> None:
    """Regression: clean process imports must not load Tavily/tiktoken/OpenAI clients."""
    module_list = ", ".join(repr(m) for m in SCREENING_MODULES)
    script = dedent(
        f"""
        import os
        import sys
        from pathlib import Path

        # Prove imports do not require API keys.
        for key in (
            "OPENAI_API_KEY",
            "TAVILY_API_KEY",
            "OPENAI_SERVICE_TIER",
            "OPENAI_TIMEOUT_SECONDS",
        ):
            os.environ.pop(key, None)

        repo = Path({str(REPO_ROOT)!r})
        sys.path.insert(0, str(repo))

        for name in ({module_list},):
            __import__(name)

        forbidden = []
        for root in ("tavily", "tiktoken", "openai"):
            if root in sys.modules or any(
                k.startswith(root + ".") for k in sys.modules
            ):
                forbidden.append(root)
        if forbidden:
            raise SystemExit(f"forbidden modules loaded: {{forbidden}}")

        # OpenAI network client must not be constructed merely by importing.
        openai_client = sys.modules.get("pipeline.openai_client")
        if openai_client is not None:
            # Module may be imported transitively only if something still pulls it;
            # even then, the SDK itself must remain unloaded until a call.
            if "openai" in sys.modules:
                raise SystemExit("openai SDK loaded during import")
        print("ok")
        """
    )
    env = os.environ.copy()
    for key in (
        "OPENAI_API_KEY",
        "TAVILY_API_KEY",
        "OPENAI_SERVICE_TIER",
        "OPENAI_TIMEOUT_SECONDS",
        "RUN_LIVE_OPENAI_TESTS",
    ):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"clean subprocess import failed\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ok" in result.stdout


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
        test_import_screening_modules_clean_subprocess,
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
