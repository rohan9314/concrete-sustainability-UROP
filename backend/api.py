"""FastAPI wrapper for the research agent."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from jobs import create_research_job, get_research_job
from questions import DEFAULT_QUESTION_SET, list_question_sets_info

app = FastAPI(title="Concrete Decarbonization Research API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    question_set: str = DEFAULT_QUESTION_SET


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/question-sets")
def question_sets() -> dict:
    sets = list_question_sets_info()
    return {
        "question_sets": sets,
        "default": DEFAULT_QUESTION_SET,
    }


@app.post("/api/research", status_code=202)
def start_research(request: ResearchRequest) -> dict:
    subject = request.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject cannot be empty.")
    return create_research_job(subject, request.question_set)


@app.get("/api/research/{job_id}")
def research_status(job_id: str) -> dict:
    job = get_research_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    response: dict = {
        "job_id": job["job_id"],
        "status": job["status"],
    }

    if job["status"] == "running" and job.get("progress"):
        response["progress"] = job["progress"]
    elif job["status"] == "completed" and job.get("result"):
        response["result"] = job["result"]
    elif job["status"] == "failed" and job.get("error"):
        response["error"] = job["error"]

    return response
