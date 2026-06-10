"""API routes for standardized TechnologyEvaluation mock endpoints."""

from fastapi import APIRouter, HTTPException

from data.mock_evaluations import build_mock_evaluation
from evaluations_store import get_evaluation, list_evaluations, save_evaluation
from schemas.technology_evaluation import (
    REQUIRED_EVALUATION_FIELDS,
    EvaluateRequest,
    TechnologyEvaluation,
)

router = APIRouter()


@router.post("/api/evaluate", response_model=TechnologyEvaluation)
def evaluate_technology(request: EvaluateRequest) -> TechnologyEvaluation:
    """
    Return a mock TechnologyEvaluation for the requested technology.

    # TODO: Replace build_mock_evaluation() with:
    # 1. Local pickle paper retrieval (paper_records.retrieve_paper_sources)
    # 2. Optional Tavily internet source retrieval (search.retrieve_internet_sources)
    # 3. OpenAI extraction mapped into TechnologyEvaluation schema
    """
    technology_name = request.technology_name.strip()
    if not technology_name:
        raise HTTPException(status_code=400, detail="technology_name is required.")

    return build_mock_evaluation(technology_name)


@router.get("/api/evaluations", response_model=list[TechnologyEvaluation])
def get_evaluations() -> list[TechnologyEvaluation]:
    return list_evaluations()


@router.get("/api/evaluations/{evaluation_id}", response_model=TechnologyEvaluation)
def get_evaluation_by_id(evaluation_id: str) -> TechnologyEvaluation:
    evaluation = get_evaluation(evaluation_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found.")
    return evaluation


@router.post("/api/evaluations", response_model=TechnologyEvaluation)
def create_evaluation(payload: dict) -> TechnologyEvaluation:
    missing = [field for field in REQUIRED_EVALUATION_FIELDS if field not in payload]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required fields: {', '.join(missing)}",
        )

    try:
        evaluation = TechnologyEvaluation.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid evaluation payload: {exc}") from exc

    return save_evaluation(evaluation)
