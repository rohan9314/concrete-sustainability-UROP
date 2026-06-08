"""In-memory async job store for research runs."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pipeline import ResearchPipelineError, run_research_pipeline

_executor = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def _set_job(job_id: str, **updates: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(updates)


def _run_job(job_id: str, subject: str, question_set: str) -> None:
    def on_progress(step: str, message: str) -> None:
        _set_job(
            job_id,
            status="running",
            progress={"step": step, "message": message},
        )

    try:
        result = run_research_pipeline(
            subject,
            question_set,
            progress_callback=on_progress,
        )
        _set_job(job_id, status="completed", result=result, progress=None)
    except ResearchPipelineError as exc:
        _set_job(
            job_id,
            status="failed",
            error={"code": exc.code, "message": exc.message},
            progress=None,
        )
    except Exception as exc:
        _set_job(
            job_id,
            status="failed",
            error={"code": "INTERNAL_ERROR", "message": str(exc)},
            progress=None,
        )


def create_research_job(subject: str, question_set: str) -> dict[str, Any]:
    """Queue a research job and return its initial status payload."""
    job_id = f"run_{uuid.uuid4().hex[:12]}"
    payload = {
        "job_id": job_id,
        "status": "queued",
        "subject": subject.strip(),
        "question_set": question_set,
        "progress": None,
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = payload.copy()

    _executor.submit(_run_job, job_id, subject.strip(), question_set)
    return {
        "job_id": job_id,
        "status": "queued",
        "subject": subject.strip(),
        "question_set": question_set,
    }


def get_research_job(job_id: str) -> dict[str, Any] | None:
    """Return the current job state for polling."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "subject": job.get("subject"),
            "question_set": job.get("question_set"),
            "progress": job.get("progress"),
            "result": job.get("result"),
            "error": job.get("error"),
        }
