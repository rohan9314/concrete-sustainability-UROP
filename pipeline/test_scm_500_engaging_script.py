"""Tests for the Engaging 500-paper SCM seed-only launch script."""

from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SH = REPO_ROOT / "scripts" / "engaging" / "run_scm_500_test.sh"
SCRIPT_PY = REPO_ROOT / "scripts" / "engaging" / "run_scm_500_test.py"


def test_launch_script_files_exist() -> None:
    assert SCRIPT_SH.is_file()
    assert SCRIPT_PY.is_file()
    text = SCRIPT_SH.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert "scm-500-test" in text
    assert "7-27 SCM Test" in text
    assert "Open-ended discovery: disabled" in text
    assert "Carbon-capture execution: disabled" in text
    assert "Internet retrieval: enabled" in text
    assert "run_scm_500_test.py" in text
    # Must not invoke carbon-capture or discovery entry points.
    assert "run_carbon_capture" not in text
    assert "run-discovery" not in text
    assert "run-all\n" not in text
    assert "carbon_capture/" not in text or "must not contain carbon_capture" in text


def test_orchestrator_constants() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("scm_500", SCRIPT_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.SAMPLE_SIZE == 500
    assert mod.RANDOM_SEED == 42
    assert mod.TOP_N == 50
    assert mod.WEB_LIMIT == 10
    assert mod.CONCURRENCY == 2
    assert len(mod.SEED_SLUGS) == 8
    assert "ternary_blends" in mod.SEED_SLUGS
    assert mod.OUT_DIRNAME == "7-27 SCM Test"
    assert mod.RUN_LABEL == "7/27 SCM Test"


def test_orchestrator_output_dir_isolated() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("scm_500", SCRIPT_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        out = mod._resolve_out_dir(REPO_ROOT)
        assert out.name == "7-27 SCM Test"
        assert "carbon_capture" not in out.parts
        mod._assert_scm_isolation(out)


def test_orchestrator_rejects_malformed_sample() -> None:
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location("scm_500", SCRIPT_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        manifests = out / "manifests"
        manifests.mkdir(parents=True)
        (manifests / "paper_sample_500.pkl").write_bytes(b"x")
        (manifests / "paper_sample_500.json").write_text(
            json.dumps(
                {
                    "sample_size": 100,
                    "random_seed": 42,
                    "paper_ids": [f"id{i}" for i in range(100)],
                },
            ),
            encoding="utf-8",
        )
        try:
            mod._validate_or_create_sample(
                out_dir=out,
                pickle_path=Path("missing.pkl"),
                dry_run=True,
                log_path=out / "log.txt",
            )
            raise AssertionError("expected SystemExit")
        except SystemExit as exc:
            assert "sample_size" in str(exc)


def test_dry_run_skips_seed_runner_and_discovery() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("scm_500", SCRIPT_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "logs").mkdir(parents=True)
        sample = out / "manifests" / "paper_sample_500.pkl"
        sample.parent.mkdir(parents=True)
        sample.write_bytes(b"")
        screening = out / "screening" / "screening_merged.jsonl"
        screening.parent.mkdir(parents=True)
        screening.write_text("", encoding="utf-8")
        with (
            patch("pipeline.scm.runner.run_seed_category") as run_seed,
            patch("pipeline.scm.runner.run_discovery") as run_disc,
            patch("pipeline.scm.runner.merge_all_evidence") as merge,
        ):
            rows = mod._run_seed_categories(
                out_dir=out,
                sample_pkl=sample,
                screening_merged=screening,
                dry_run=True,
                log_path=out / "logs" / "t.log",
            )
            mod._merge_seed_outputs(out_dir=out, dry_run=True, log_path=out / "logs" / "t.log")
            assert len(rows) == 8
            run_seed.assert_not_called()
            run_disc.assert_not_called()
            merge.assert_not_called()


def test_shell_script_has_conservative_slurm_resources() -> None:
    text = SCRIPT_SH.read_text(encoding="utf-8")
    assert "#SBATCH --nodes=1" in text
    assert "#SBATCH --cpus-per-task=4" in text
    assert "#SBATCH --mem=64G" in text
    assert "#SBATCH --time=24:00:00" in text
    assert "EXTRACTION_CONCURRENCY" in text


def test_orchestrator_ast_has_no_discovery_call_outside_guard() -> None:
    tree = ast.parse(SCRIPT_PY.read_text(encoding="utf-8"))
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.append(func.id)
            elif isinstance(func, ast.Attribute):
                calls.append(func.attr)
    assert "run_discovery" not in calls
    assert "run_scm_pipeline" not in calls


def main() -> int:
    tests = [
        test_launch_script_files_exist,
        test_orchestrator_constants,
        test_orchestrator_output_dir_isolated,
        test_orchestrator_rejects_malformed_sample,
        test_dry_run_skips_seed_runner_and_discovery,
        test_shell_script_has_conservative_slurm_resources,
        test_orchestrator_ast_has_no_discovery_call_outside_guard,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} Engaging SCM 500-test script checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
