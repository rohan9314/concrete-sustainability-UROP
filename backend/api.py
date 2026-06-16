"""FastAPI wrapper for the research agent."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from evaluations_routes import router as evaluations_router
from intelligence_constants import INTELLIGENCE_OPTIONS
from jobs import create_research_job, get_research_job
from questions import DEFAULT_QUESTION_SET, list_question_sets_info
from schemas.technology_intelligence import ResearchFilters

app = FastAPI(title="Concrete Decarbonization Research API", version="1.0.0")
app.include_router(evaluations_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://localhost:8081",
    ],
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResearchRequest(BaseModel):
    subject: str = Field(..., min_length=1)
    question_set: str = DEFAULT_QUESTION_SET
    filters: ResearchFilters = Field(default_factory=ResearchFilters)
    include_legacy_qa: bool = False


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


@app.get("/api/intelligence-options")
def intelligence_options() -> dict:
    return INTELLIGENCE_OPTIONS


@app.post("/api/research", status_code=202)
def start_research(request: ResearchRequest) -> dict:
    subject = request.subject.strip()
    if not subject:
        raise HTTPException(status_code=400, detail="Subject cannot be empty.")
    return create_research_job(
        subject,
        request.question_set,
        filters=request.filters.model_dump(),
        include_legacy_qa=request.include_legacy_qa,
    )


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
