"""Isolation tests: SCM must not invoke or depend on carbon-capture execution."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.scm.config import (
    assert_scm_output_isolated,
    carbon_capture_output_root,
    scm_output_root,
)
from pipeline.scm.extraction import ScmEvidenceRow
from pipeline.scm.merge import NonScmRecordError, conservative_merge_rows
from pipeline.scm.runner import (
    ScmRunConfig,
    print_dry_run,
    run_all_seed_categories,
    run_discovery,
    run_seed_category,
)
from pipeline.scm.schema import CATEGORY_LABEL, NA


def test_scm_seed_command_does_not_call_carbon_capture_runner() -> None:
    config = ScmRunConfig(
        slugs=["slag_cement"],
        stage="run-seed-category",
        test_mode=True,
        dry_run=True,
        output_dir=scm_output_root(test_mode=True),
    )
    with patch("pipeline.carbon_capture_runner.run_carbon_capture_pipeline") as cc:
        run_seed_category(config, "slag_cement")
        cc.assert_not_called()


def test_scm_discovery_does_not_call_carbon_capture_runner() -> None:
    config = ScmRunConfig(
        stage="discover",
        run_discovery=True,
        test_mode=True,
        dry_run=True,
        output_dir=scm_output_root(test_mode=True),
    )
    with patch("pipeline.carbon_capture_runner.run_carbon_capture_pipeline") as cc:
        run_discovery(config)
        cc.assert_not_called()


def test_scm_and_cc_output_paths_differ() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        os.environ.pop("SCM_OUTPUT_ROOT", None)
        os.environ.pop("CARBON_CAPTURE_OUTPUT_ROOT", None)
        scm = scm_output_root()
        cc = carbon_capture_output_root()
        assert scm.resolve() != cc.resolve()
        assert scm.name == "scm"
        assert cc.name == "carbon_capture"


def test_scm_merge_rejects_carbon_capture_records() -> None:
    bad = ScmEvidenceRow(
        record_id="cc:1",
        category="Carbon Capture",
        category_id="carbon_capture",
        seed_category=NA,
        source_type="Literature",
        source_origin="literature",
    )
    try:
        conservative_merge_rows([bad], [])
        raise AssertionError("expected NonScmRecordError")
    except NonScmRecordError:
        pass


def test_scm_retrieval_rejects_cc_screening_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        scm_root = scm_output_root()
        cc_screen = Path(tmp) / "carbon_capture" / "screening_merged.jsonl"
        cc_screen.parent.mkdir(parents=True, exist_ok=True)
        cc_screen.write_text("{}\n", encoding="utf-8")
        config = ScmRunConfig(
            slugs=["slag_cement"],
            screening_results=str(cc_screen),
            output_dir=scm_root,
            test_mode=True,
        )
        try:
            config.validated_screening_path()
            raise AssertionError("expected ValueError for CC screening path")
        except ValueError as exc:
            assert "outside SCM" in str(exc) or "carbon-capture" in str(exc).lower()


def test_scm_resume_checks_only_scm_checkpoints() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        scm_root = scm_output_root()
        (scm_root / "checkpoints").mkdir(parents=True, exist_ok=True)
        cc_root = carbon_capture_output_root()
        (cc_root / "checkpoints").mkdir(parents=True, exist_ok=True)
        cc_marker = cc_root / "checkpoints" / "slag_cement_literature.done"
        cc_marker.write_text("complete\n", encoding="utf-8")
        scm_marker = scm_root / "checkpoints" / "slag_cement_literature.done"
        assert not scm_marker.exists()
        # Presence of a CC checkpoint must not imply SCM completion.
        from pipeline.scm.logging_utils import checkpoint_exists

        assert checkpoint_exists(cc_marker)
        assert not checkpoint_exists(scm_marker)


def test_scm_test_run_does_not_modify_cc_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        cc_root = carbon_capture_output_root()
        cc_root.mkdir(parents=True, exist_ok=True)
        sentinel = cc_root / "amine_absorption_answers.csv"
        sentinel.write_text("category,subcategory\nCarbon Capture,amine\n", encoding="utf-8")
        mtime_before = sentinel.stat().st_mtime
        time.sleep(0.05)

        config = ScmRunConfig(
            slugs=["slag_cement"],
            stage="run-seed-category",
            test_mode=True,
            dry_run=True,
            output_dir=scm_output_root(test_mode=True),
        )
        run_seed_category(config, "slag_cement")
        mtime_after = sentinel.stat().st_mtime
        assert mtime_before == mtime_after
        assert sentinel.read_text() == "category,subcategory\nCarbon Capture,amine\n"


def test_importing_scm_entrypoint_does_not_load_cc_config() -> None:
    import importlib

    # Ensure carbon_capture_config is not a prerequisite of importing scm.__main__.
    sys.modules.pop("pipeline.carbon_capture_config", None)
    sys.modules.pop("pipeline.carbon_capture_runner", None)
    import pipeline.scm.__main__ as scm_main

    importlib.reload(scm_main)
    assert "pipeline.carbon_capture_runner" not in sys.modules


def test_one_subcategory_does_not_run_others() -> None:
    called: list[str] = []

    def fake_run(config, slug):
        called.append(slug)
        return MagicMock()

    config = ScmRunConfig(
        slugs=["slag_cement"],
        stage="run-all-seed-categories",
        test_mode=True,
        dry_run=False,
        output_dir=scm_output_root(test_mode=True),
    )
    # dry_run short-circuits before loop; force non-dry and patch run_seed_category
    with patch("pipeline.scm.runner.run_seed_category", side_effect=fake_run):
        run_all_seed_categories(
            ScmRunConfig(
                slugs=["slag_cement"],
                stage="run-all-seed-categories",
                test_mode=True,
                output_dir=config.output_dir,
            ),
        )
    assert called == ["slag_cement"]


def test_all_seed_categories_does_not_run_discovery() -> None:
    with (
        patch("pipeline.scm.runner.run_seed_category", return_value=MagicMock()) as seeds,
        patch("pipeline.scm.runner.run_discovery") as discovery,
    ):
        run_all_seed_categories(
            ScmRunConfig(
                slugs=["slag_cement", "silica_fume"],
                stage="run-all-seed-categories",
                test_mode=True,
                output_dir=scm_output_root(test_mode=True),
            ),
        )
        assert seeds.call_count == 2
        discovery.assert_not_called()


def test_run_all_seed_categories_stage_runs_literature_not_web() -> None:
    """Orchestrator stage must extract literature; --skip-web must keep web empty."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        out = Path(tmp) / "scm"
        out.mkdir(parents=True, exist_ok=True)
        config = ScmRunConfig(
            slugs=["slag_cement"],
            stage="run-all-seed-categories",
            test_mode=True,
            skip_web=True,
            skip_literature=False,
            output_dir=out,
        )
        with (
            patch(
                "pipeline.scm.runner.run_seed_literature",
                return_value=[],
            ) as lit,
            patch("pipeline.scm.runner.run_seed_web") as web,
            patch(
                "pipeline.scm.runner.export_seed_category_outputs",
                return_value=MagicMock(),
            ) as export,
        ):
            run_seed_category(config, "slag_cement")
            lit.assert_called_once()
            web.assert_not_called()
            export.assert_called_once()


def test_resume_flag_skips_completed_literature_in_test_mode() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        out = Path(tmp) / "scm"
        lit_dir = out / "literature"
        ckpt = out / "checkpoints"
        lit_dir.mkdir(parents=True)
        ckpt.mkdir(parents=True)
        lit_path = lit_dir / "slag_cement_literature.jsonl"
        lit_path.write_text(
            '{"type":"scm_evidence_meta","row_count":0}\n',
            encoding="utf-8",
        )
        (ckpt / "slag_cement_literature.done").write_text("complete\n", encoding="utf-8")
        config = ScmRunConfig(
            slugs=["slag_cement"],
            stage="run-seed-category",
            test_mode=True,
            resume=True,
            skip_web=True,
            output_dir=out,
        )
        with (
            patch("pipeline.scm.runner.retrieve_seed_category_papers") as retrieve,
            patch(
                "pipeline.scm.runner.export_seed_category_outputs",
                return_value=MagicMock(),
            ),
        ):
            run_seed_category(config, "slag_cement")
            retrieve.assert_not_called()


def test_discovery_does_not_run_seed_extraction() -> None:
    with (
        patch("pipeline.scm.runner.run_seed_category") as seeds,
        patch("pipeline.scm.runner.retrieve_discovery_papers", return_value=[]),
        patch("pipeline.scm.runner.discover_discovery_web_sources", return_value=[]),
        patch("pipeline.scm.runner.extract_discovery_papers_parallel", return_value=[]),
        patch("pipeline.scm.runner.write_jsonl_discovery"),
        patch("pipeline.scm.runner.export_discovery_evidence_csv"),
    ):
        run_discovery(
            ScmRunConfig(
                stage="discover",
                run_discovery=True,
                test_mode=True,
                skip_web=True,
                output_dir=scm_output_root(test_mode=True),
            ),
        )
        seeds.assert_not_called()


def test_output_root_collision_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        os.environ["SCM_OUTPUT_ROOT"] = str(Path(tmp) / "carbon_capture")
        os.environ["CARBON_CAPTURE_OUTPUT_ROOT"] = str(Path(tmp) / "carbon_capture")
        try:
            scm_output_root()
            raise AssertionError("expected collision ValueError")
        except ValueError:
            pass
        finally:
            os.environ.pop("SCM_OUTPUT_ROOT", None)
            os.environ.pop("CARBON_CAPTURE_OUTPUT_ROOT", None)


def test_scm_works_without_cc_output_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        os.environ.pop("CARBON_CAPTURE_OUTPUT_ROOT", None)
        cc = Path(tmp) / "carbon_capture"
        assert not cc.exists()
        root = scm_output_root(test_mode=True)
        root.mkdir(parents=True, exist_ok=True)
        assert root.exists()
        assert not cc.exists()


def test_scm_works_when_cc_outputs_readonly() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        cc = carbon_capture_output_root()
        cc.mkdir(parents=True, exist_ok=True)
        sentinel = cc / "locked.csv"
        sentinel.write_text("x\n", encoding="utf-8")
        os.chmod(sentinel, 0o444)
        os.chmod(cc, 0o555)
        try:
            config = ScmRunConfig(
                slugs=["slag_cement"],
                test_mode=True,
                dry_run=True,
                output_dir=scm_output_root(test_mode=True),
            )
            run_seed_category(config, "slag_cement")
            assert sentinel.read_text() == "x\n"
        finally:
            os.chmod(cc, 0o755)
            os.chmod(sentinel, 0o644)


def test_cluster_scripts_have_no_cc_entrypoints() -> None:
    scripts = REPO_ROOT / "scripts" / "engaging" / "scm"
    for path in scripts.glob("*.sh"):
        text = path.read_text()
        assert "run_carbon_capture" not in text
        assert "carbon_capture/" not in text
        assert "pipeline.scm" in text or "SCM_OUTPUT_ROOT" in text


def test_dry_run_mentions_cc_disabled(capsys=None) -> None:
    config = ScmRunConfig(
        slugs=["slag_cement"],
        stage="run-all",
        test_mode=True,
        dry_run=True,
        output_dir=scm_output_root(test_mode=True),
    )
    # Capture print output without pytest capsys dependency.
    from io import StringIO
    import contextlib

    buf = StringIO()
    with contextlib.redirect_stdout(buf):
        print_dry_run(config)
    text = buf.getvalue()
    assert "Carbon-capture execution: disabled" in text
    assert "will not be read or modified" in text
    assert CATEGORY_LABEL in text or "SCM" in text


def test_pipeline_run_requires_category() -> None:
    from pipeline import run as pipeline_run

    try:
        pipeline_run.main([])
        raise AssertionError("expected SystemExit/error")
    except SystemExit as exc:
        assert exc.code == 2


def test_assert_isolated_helper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = tmp
        good = Path(tmp) / "scm"
        good.mkdir()
        assert assert_scm_output_isolated(good) == good.resolve()


def main() -> int:
    tests = [
        test_scm_seed_command_does_not_call_carbon_capture_runner,
        test_scm_discovery_does_not_call_carbon_capture_runner,
        test_scm_and_cc_output_paths_differ,
        test_scm_merge_rejects_carbon_capture_records,
        test_scm_retrieval_rejects_cc_screening_path,
        test_scm_resume_checks_only_scm_checkpoints,
        test_scm_test_run_does_not_modify_cc_files,
        test_importing_scm_entrypoint_does_not_load_cc_config,
        test_one_subcategory_does_not_run_others,
        test_all_seed_categories_does_not_run_discovery,
        test_run_all_seed_categories_stage_runs_literature_not_web,
        test_resume_flag_skips_completed_literature_in_test_mode,
        test_discovery_does_not_run_seed_extraction,
        test_output_root_collision_rejected,
        test_scm_works_without_cc_output_dir,
        test_scm_works_when_cc_outputs_readonly,
        test_cluster_scripts_have_no_cc_entrypoints,
        test_dry_run_mentions_cc_disabled,
        test_pipeline_run_requires_category,
        test_assert_isolated_helper,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"All {len(tests)} SCM isolation tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
