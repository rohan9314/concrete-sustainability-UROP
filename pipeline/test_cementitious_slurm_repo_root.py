#!/usr/bin/env python3
"""Regression tests for Slurm spool-safe REPO_ROOT resolution."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGAGING = REPO_ROOT / "scripts" / "engaging"

SBATCH_EXECUTED_MARKERS = (
    "#SBATCH",
    "sbatch --parsable",
)


def _tracked_cementitious_sbatch_scripts() -> list[Path]:
    paths: list[Path] = []
    for path in sorted(ENGAGING.glob("730_cementitious_*.sh")):
        text = path.read_text(encoding="utf-8")
        if "#SBATCH" in text or path.name.endswith("_array.sh") or "preprocess" in path.name:
            paths.append(path)
    # Also orchestrators / merges that may be submitted as batch files or wrap targets
    # but still must not rely on BASH_SOURCE for helpers when exported via REPO_ROOT.
    for name in [
        "730_cementitious_orchestrate_after_screen.sh",
        "730_cementitious_orchestrate_web.sh",
        "730_cementitious_finalize.sh",
        "730_cementitious_merge_screening.sh",
        "730_cementitious_merge_extractions.sh",
        "730_cementitious_merge_web_search.sh",
        "730_cementitious_merge_web_extract.sh",
        "730_cementitious_merge_literature_web.sh",
        "730_cementitious_dedupe_qc.sh",
        "730_cementitious_export.sh",
        "730_cementitious_rank_plan_extract.sh",
        "730_cementitious_plan_web_queries.sh",
        "730_cementitious_plan_web_extract.sh",
        "730_cementitious_plan.sh",
        "730_cementitious_preprocess_plan.sh",
        "730_cementitious_screen_array.sh",
        "730_cementitious_extract_array.sh",
        "730_cementitious_web_search_array.sh",
        "730_cementitious_web_extract_array.sh",
    ]:
        path = ENGAGING / name
        if path.is_file() and path not in paths:
            paths.append(path)
    return paths


class RepoRootHelperTests(unittest.TestCase):
    def _make_fake_repo(self, root: Path) -> Path:
        engaging = root / "scripts" / "engaging"
        engaging.mkdir(parents=True)
        (root / "pipeline" / "cementitious").mkdir(parents=True)
        (root / "pipeline" / "cementitious" / "__init__.py").write_text('""test""\n', encoding="utf-8")
        # Copy the real helpers into the fake repo.
        for name in (
            "_cementitious_repo_root.sh",
            "_resolve_cementitious_out.sh",
            "_cementitious_slurm_diagnostics.sh",
        ):
            shutil.copy2(ENGAGING / name, engaging / name)
        (engaging / "run_cementitious_full_workflow.sh").write_text(
            "#!/bin/bash\necho launcher\n", encoding="utf-8"
        )
        return engaging

    def test_valid_repo_root_and_slurm_submit_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo with spaces" / "concrete"
            engaging = self._make_fake_repo(root)
            env = os.environ.copy()
            env.pop("REPO_ROOT", None)
            env.pop("SLURM_SUBMIT_DIR", None)
            # Missing both -> fail
            script = f"""
set -euo pipefail
source "{engaging / "_cementitious_repo_root.sh"}"
if cementitious_resolve_repo_root missing; then exit 10; else exit 0; fi
"""
            # Can't source from engaging without REPO_ROOT - source by absolute path of fake helper
            proc = subprocess.run(
                ["bash", "-c", script],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            # Valid REPO_ROOT
            env["REPO_ROOT"] = str(root)
            proc = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{engaging / "_cementitious_repo_root.sh"}"; '
                    f'cementitious_resolve_repo_root ok; echo "$REPO_ROOT"',
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()).resolve(), root.resolve())

            # Invalid REPO_ROOT + valid SLURM_SUBMIT_DIR
            env["REPO_ROOT"] = str(Path(tmp) / "not-a-repo")
            env["SLURM_SUBMIT_DIR"] = str(root)
            proc = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{engaging / "_cementitious_repo_root.sh"}"; '
                    f'cementitious_resolve_repo_root fallback; echo "$REPO_ROOT"',
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()).resolve(), root.resolve())

    def test_spool_copy_uses_exported_repo_root_not_spool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "real_repo"
            engaging = self._make_fake_repo(root)
            # Minimal preprocess-like script copied into a spool path.
            spool = Path(tmp) / "var" / "spool" / "slurmd" / "job123"
            spool.mkdir(parents=True)
            slurm_script = spool / "slurm_script"
            # Copy real preprocess bootstrap pattern + a probe for helper path.
            body = f"""#!/bin/bash
set -euo pipefail
export CEMENTITIOUS_STAGE=preprocess_plan
_cem_helper=""
for _cem_cand in "${{REPO_ROOT:-}}" "${{SLURM_SUBMIT_DIR:-}}"; do
  [[ -n "${{_cem_cand}}" ]] || continue
  if [[ -f "${{_cem_cand%/}}/scripts/engaging/_cementitious_repo_root.sh" ]]; then
    _cem_helper="${{_cem_cand%/}}/scripts/engaging/_cementitious_repo_root.sh"
    break
  fi
done
[[ -n "${{_cem_helper}}" ]] || exit 2
source "${{_cem_helper}}"
cementitious_resolve_repo_root preprocess_plan || exit 3
cd "$REPO_ROOT"
cementitious_source_engaging_helper "_resolve_cementitious_out.sh" preprocess_plan || exit 4
cementitious_source_engaging_helper "_cementitious_slurm_diagnostics.sh" preprocess_plan || exit 5
# Prove helpers came from REPO_ROOT, not spool.
echo "REPO_ROOT=$REPO_ROOT"
echo "HELPER_DIR=$REPO_ROOT/scripts/engaging"
test -f "$REPO_ROOT/scripts/engaging/_resolve_cementitious_out.sh"
case "$REPO_ROOT" in
  */var/spool/slurmd/*) exit 6 ;;
esac
# Ensure we did not pick the spool dirname of this script.
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
echo "SCRIPT_DIR=$SCRIPT_DIR"
[[ "$SCRIPT_DIR" == *"/var/spool/slurmd/"* ]] || exit 7
[[ "$REPO_ROOT" != "$SCRIPT_DIR" ]] || exit 8
"""
            slurm_script.write_text(body, encoding="utf-8")
            slurm_script.chmod(slurm_script.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env["REPO_ROOT"] = str(root)
            env.pop("SLURM_SUBMIT_DIR", None)
            proc = subprocess.run(
                ["bash", str(slurm_script)],
                env=env,
                capture_output=True,
                text=True,
                cwd=str(spool),
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn(f"REPO_ROOT={root.resolve()}", proc.stdout.replace(str(root), str(root.resolve())) or proc.stdout)
            self.assertIn("/var/spool/slurmd/", proc.stdout)
            self.assertNotIn(str(spool / "_resolve_cementitious_out.sh"), proc.stdout)

    def test_neither_path_valid_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            engaging = self._make_fake_repo(root)
            env = os.environ.copy()
            env["REPO_ROOT"] = str(Path(tmp) / "bad")
            env["SLURM_SUBMIT_DIR"] = str(Path(tmp) / "also-bad")
            proc = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{engaging / "_cementitious_repo_root.sh"}"; cementitious_resolve_repo_root boom',
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("repository root could not be resolved", proc.stderr)

    def test_no_user_specific_home_paths_in_helpers(self) -> None:
        text = (ENGAGING / "_cementitious_repo_root.sh").read_text(encoding="utf-8")
        self.assertNotIn("/home/rohan931", text)
        self.assertNotIn("rohan931", text)

    def test_static_no_bash_source_helper_sourcing_in_sbatch_scripts(self) -> None:
        banned = re.compile(
            r'source\s+["\']?\$\(_?SCRIPT_DIR\)/_(?:resolve_cementitious_out|cementitious_slurm_diagnostics)\.sh'
            r'|source\s+["\']?\$\(cd "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)"'
            r'|source\s+".*\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\).*_(?:resolve_cementitious_out|cementitious_slurm_diagnostics)\.sh'
            r'|source\s+"\$_SCRIPT_DIR/_(?:resolve_cementitious_out|cementitious_slurm_diagnostics)\.sh"'
            r'|source\s+"\$\(dirname "\$0"\)/'
        )
        bash_source_repo = re.compile(
            r'REPO_ROOT="\$\{REPO_ROOT:-\$\(cd "\$_SCRIPT_DIR/\.\./\.\." && pwd\)\}"'
        )
        offenders: list[str] = []
        for path in _tracked_cementitious_sbatch_scripts():
            text = path.read_text(encoding="utf-8")
            if banned.search(text) or bash_source_repo.search(text):
                offenders.append(path.name)
            # Must not source helpers via dirname BASH_SOURCE alone
            if re.search(
                r'source\s+".*\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\).*/_(?:resolve_cementitious_out|cementitious_slurm_diagnostics)\.sh"',
                text,
            ):
                offenders.append(path.name)
            # Prefer absolute REPO_ROOT helper sourcing
            if "cementitious_source_engaging_helper" not in text and "_resolve_cementitious_out.sh" in text:
                # plan/full_pipeline wrappers may not source resolve
                if path.name not in {"730_cementitious_full_pipeline.sh"}:
                    offenders.append(f"{path.name}:missing_helper_fn")
        self.assertEqual(offenders, [], f"Vulnerable scripts: {offenders}")

    def test_launcher_propagates_repo_root_in_dry_run_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp) / "results parent"
            results.mkdir()
            pickle = Path(tmp) / "tiny.pkl"
            # Minimal pickle for preflight path existence.
            import pickle as pkl

            pkl.dump([], pickle.open("wb"))
            env = os.environ.copy()
            env.update(
                {
                    "OPENAI_API_KEY": "sk-test-not-used",
                    "TAVILY_API_KEY": "tvly-test-not-used",
                    "PICKLE_PATH": str(pickle),
                    "RESULTS_ROOT": str(results),
                    "REPO_ROOT": str(REPO_ROOT),
                }
            )
            proc = subprocess.run(
                ["bash", str(ENGAGING / "run_cementitious_full_workflow.sh"), "--pilot", "--dry-run"],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            self.assertIn(f"REPO_ROOT={REPO_ROOT}", proc.stdout)
            self.assertIn("preprocess_sbatch:", proc.stdout)
            self.assertIn("--chdir=", proc.stdout)
            self.assertIn("_resolve_cementitious_out.sh", proc.stdout)
            # Manifest must not contain secret values
            pilot_out = results / "cementitious_engaging_pilot" / "7-30 results"
            repo_meta = pilot_out / "metadata" / "repo_root.json"
            self.assertTrue(repo_meta.is_file(), repo_meta)
            payload = repo_meta.read_text(encoding="utf-8")
            self.assertIn(str(REPO_ROOT), payload)
            self.assertNotIn("sk-test-not-used", payload)
            self.assertNotIn("tvly-test-not-used", payload)
            self.assertIn('"secrets_included": false', payload)


if __name__ == "__main__":
    unittest.main()
