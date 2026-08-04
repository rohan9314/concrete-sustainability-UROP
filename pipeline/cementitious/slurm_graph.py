"""Dry-run model of the Cementitious Materials Slurm dependency graph."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GraphJob:
    job_id: str
    job_name: str
    stage: str
    branch: str
    dependency_type: str
    parent_job_ids: list[str] = field(default_factory=list)
    array_range: str | None = None
    submission_command: str = ""
    expected_outputs: list[str] = field(default_factory=list)
    log_path: str = ""


def build_dry_run_dependency_graph(
    *,
    run_mode: str = "literature-and-web",
    screen_array: str = "0-3",
    extract_array: str = "0-1",
    web_search_array: str = "0-2",
    web_extract_array: str = "0-1",
    include_ccs_migrate: bool = False,
) -> dict[str, Any]:
    """
    Return the intended afterok dependency chain without submitting jobs.

    Combined mode uses a short finalize-submitter that chains on the actual
    literature and web terminal merge job IDs (no marker polling).
    """
    jobs: list[GraphJob] = []
    next_id = 1000

    def alloc(name: str) -> str:
        nonlocal next_id
        jid = str(next_id)
        next_id += 1
        return jid

    need_lit = run_mode in {"literature-only", "literature_only", "literature-and-web", "literature_and_web"}
    need_web = run_mode in {"web-only", "web_only", "literature-and-web", "literature_and_web"}
    combined = need_lit and need_web

    lit_terminal = None
    web_terminal = None

    if need_lit:
        screen = alloc("screen")
        jobs.append(
            GraphJob(
                job_id=screen,
                job_name="cm-screen",
                stage="screen",
                branch="literature",
                dependency_type="none",
                array_range=screen_array,
                submission_command=f"sbatch --array={screen_array} 730_cementitious_screen_array.sh",
                expected_outputs=["metadata/screening_shards/screening_shard_*.jsonl"],
                log_path="logs/cm-screen-%j.out",
            )
        )
        merge_screen = alloc("screen_merge")
        jobs.append(
            GraphJob(
                job_id=merge_screen,
                job_name="cm-merge-screen",
                stage="screen_merge",
                branch="literature",
                dependency_type="afterok",
                parent_job_ids=[screen],
                submission_command="sbatch --dependency=afterok:... 730_cementitious_merge_screening.sh",
                expected_outputs=["metadata/screening_results.jsonl", "checkpoints/screen_merge.complete"],
                log_path="logs/cm-merge-screen-%j.out",
            )
        )
        lit_orch = alloc("lit_orchestrate")
        jobs.append(
            GraphJob(
                job_id=lit_orch,
                job_name="cm-orchestrate-lit",
                stage="orchestrate_lit",
                branch="literature",
                dependency_type="afterok",
                parent_job_ids=[merge_screen],
                submission_command="sbatch --dependency=afterok:... 730_cementitious_orchestrate_after_screen.sh",
                expected_outputs=["metadata/literature_terminal_job_id.txt"],
                log_path="logs/cm-orchestrate-lit-%j.out",
            )
        )
        extract = alloc("extract")
        jobs.append(
            GraphJob(
                job_id=extract,
                job_name="cm-extract",
                stage="extract",
                branch="literature",
                dependency_type="afterok",
                parent_job_ids=[lit_orch],
                array_range=extract_array,
                submission_command=f"sbatch --array={extract_array} 730_cementitious_extract_array.sh",
                expected_outputs=["metadata/extraction_shards/extraction_shard_*.jsonl"],
                log_path="logs/cm-extract-%j.out",
            )
        )
        merge_extract = alloc("extract_merge")
        jobs.append(
            GraphJob(
                job_id=merge_extract,
                job_name="cm-merge-extract",
                stage="extract_merge",
                branch="literature",
                dependency_type="afterok",
                parent_job_ids=[extract],
                submission_command="sbatch --dependency=afterok:... 730_cementitious_merge_extractions.sh",
                expected_outputs=["metadata/extracted_records_raw.jsonl", "checkpoints/extract_merge.complete"],
                log_path="logs/cm-merge-extract-%j.out",
            )
        )
        lit_terminal = merge_extract
        if not combined:
            prev = merge_extract
            dedupe = alloc("dedupe_qc")
            jobs.append(
                GraphJob(
                    job_id=dedupe,
                    job_name="cm-dedupe-qc",
                    stage="dedupe_qc",
                    branch="literature",
                    dependency_type="afterok",
                    parent_job_ids=[prev],
                    expected_outputs=["metadata/merged_records.csv"],
                    log_path="logs/cm-dedupe-qc-%j.out",
                )
            )
            prev = dedupe
            if include_ccs_migrate:
                mig = alloc("migrate_ccs")
                jobs.append(
                    GraphJob(
                        job_id=mig,
                        job_name="cm-migrate-ccs",
                        stage="migrate_ccs",
                        branch="literature",
                        dependency_type="afterok",
                        parent_job_ids=[prev],
                        expected_outputs=["metadata/migrated_carbon_capture_records.csv"],
                        log_path="logs/cm-migrate-ccs-%j.out",
                    )
                )
                prev = mig
            export = alloc("export")
            jobs.append(
                GraphJob(
                    job_id=export,
                    job_name="cm-export",
                    stage="export",
                    branch="literature",
                    dependency_type="afterok",
                    parent_job_ids=[prev],
                    expected_outputs=["all_records/validation_report.json"],
                    log_path="logs/cm-export-%j.out",
                )
            )

    if need_web:
        web_search = alloc("web_search")
        jobs.append(
            GraphJob(
                job_id=web_search,
                job_name="cm-web-search",
                stage="web_search",
                branch="web",
                dependency_type="none",
                array_range=web_search_array,
                submission_command=f"sbatch --array={web_search_array} 730_cementitious_web_search_array.sh",
                expected_outputs=["metadata/web_search_shards/web_search_shard_*.jsonl"],
                log_path="logs/cm-web-search-%j.out",
            )
        )
        web_orch = alloc("web_orchestrate")
        jobs.append(
            GraphJob(
                job_id=web_orch,
                job_name="cm-orchestrate-web",
                stage="orchestrate_web",
                branch="web",
                dependency_type="afterok",
                parent_job_ids=[web_search],
                submission_command="sbatch --dependency=afterok:... 730_cementitious_orchestrate_web.sh",
                expected_outputs=["metadata/web_terminal_job_id.txt"],
                log_path="logs/cm-orchestrate-web-%j.out",
            )
        )
        web_extract = alloc("web_extract")
        jobs.append(
            GraphJob(
                job_id=web_extract,
                job_name="cm-web-extract",
                stage="web_extract",
                branch="web",
                dependency_type="afterok",
                parent_job_ids=[web_orch],
                array_range=web_extract_array,
                expected_outputs=["metadata/web_extraction_shards/web_extraction_shard_*.jsonl"],
                log_path="logs/cm-web-extract-%j.out",
            )
        )
        web_merge = alloc("web_extract_merge")
        jobs.append(
            GraphJob(
                job_id=web_merge,
                job_name="cm-merge-web-extract",
                stage="web_extract_merge",
                branch="web",
                dependency_type="afterok",
                parent_job_ids=[web_extract],
                expected_outputs=["metadata/web_records_raw.jsonl", "checkpoints/web_extract_merge.complete"],
                log_path="logs/cm-merge-web-extract-%j.out",
            )
        )
        web_terminal = web_merge
        if not combined:
            prev = web_merge
            for stage, name in (
                ("merge_literature_web", "cm-merge-lit-web"),
                ("dedupe_qc", "cm-dedupe-qc"),
            ):
                jid = alloc(stage)
                jobs.append(
                    GraphJob(
                        job_id=jid,
                        job_name=name,
                        stage=stage,
                        branch="web",
                        dependency_type="afterok",
                        parent_job_ids=[prev],
                        log_path=f"logs/{name}-%j.out",
                    )
                )
                prev = jid
            if include_ccs_migrate:
                mig = alloc("migrate_ccs")
                jobs.append(
                    GraphJob(
                        job_id=mig,
                        job_name="cm-migrate-ccs",
                        stage="migrate_ccs",
                        branch="web",
                        dependency_type="afterok",
                        parent_job_ids=[prev],
                        log_path="logs/cm-migrate-ccs-%j.out",
                    )
                )
                prev = mig
            export = alloc("export")
            jobs.append(
                GraphJob(
                    job_id=export,
                    job_name="cm-export",
                    stage="export",
                    branch="web",
                    dependency_type="afterok",
                    parent_job_ids=[prev],
                    log_path="logs/cm-export-%j.out",
                )
            )

    if combined:
        # Short finalize-submit depends on orchestrators only long enough to obtain
        # terminal job IDs, then submits real afterok chain and exits (no polling).
        finalize_submit = alloc("finalize_submit")
        jobs.append(
            GraphJob(
                job_id=finalize_submit,
                job_name="cm-finalize-submit",
                stage="finalize_submit",
                branch="combined",
                dependency_type="afterok",
                parent_job_ids=[
                    j.job_id for j in jobs if j.stage in {"orchestrate_lit", "orchestrate_web"}
                ],
                submission_command="sbatch --dependency=afterok:orch_lit:orch_web 730_cementitious_finalize.sh",
                expected_outputs=["metadata/submitted_jobs.json"],
                log_path="logs/cm-finalize-submit-%j.out",
            )
        )
        assert lit_terminal and web_terminal
        merge = alloc("merge_literature_web")
        jobs.append(
            GraphJob(
                job_id=merge,
                job_name="cm-merge-lit-web",
                stage="merge_literature_web",
                branch="combined",
                dependency_type="afterok",
                parent_job_ids=[lit_terminal, web_terminal],
                submission_command=f"sbatch --dependency=afterok:{lit_terminal}:{web_terminal} merge_literature_web",
                expected_outputs=["metadata/combined_records_pre_dedupe.jsonl"],
                log_path="logs/cm-merge-lit-web-%j.out",
            )
        )
        prev = merge
        dedupe = alloc("dedupe_qc")
        jobs.append(
            GraphJob(
                job_id=dedupe,
                job_name="cm-dedupe-qc",
                stage="dedupe_qc",
                branch="combined",
                dependency_type="afterok",
                parent_job_ids=[prev],
                log_path="logs/cm-dedupe-qc-%j.out",
            )
        )
        prev = dedupe
        if include_ccs_migrate:
            mig = alloc("migrate_ccs")
            jobs.append(
                GraphJob(
                    job_id=mig,
                    job_name="cm-migrate-ccs",
                    stage="migrate_ccs",
                    branch="combined",
                    dependency_type="afterok",
                    parent_job_ids=[prev],
                    log_path="logs/cm-migrate-ccs-%j.out",
                )
            )
            prev = mig
        export = alloc("export")
        jobs.append(
            GraphJob(
                job_id=export,
                job_name="cm-export",
                stage="export",
                branch="combined",
                dependency_type="afterok",
                parent_job_ids=[prev],
                expected_outputs=["all_records/validation_report.json", "pending_taxonomy_review/"],
                log_path="logs/cm-export-%j.out",
            )
        )

    return {
        "run_mode": run_mode,
        "finalization_strategy": "afterok_on_terminal_branch_jobs",
        "uses_marker_poll_finalizer": False,
        "literature_terminal_job_id": lit_terminal,
        "web_terminal_job_id": web_terminal,
        "jobs": [asdict(j) for j in jobs],
    }
