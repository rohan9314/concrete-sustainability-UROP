"""Pydantic models for structured technology evaluation output."""

from pydantic import BaseModel, Field, field_validator


class SourceMetadata(BaseModel):
    """Bibliographic metadata for a retrieved source."""

    authors: list[str] = Field(default_factory=list)
    year: str = ""
    journal: str = ""
    doi: str = ""

    @field_validator("authors", mode="before")
    @classmethod
    def normalize_authors(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            return [] if not cleaned or cleaned == "Not Found" else [cleaned]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("year", "journal", "doi", mode="before")
    @classmethod
    def normalize_text_fields(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class Source(BaseModel):
    """A reference source supporting a specific answer."""

    title: str = ""
    url: str = ""
    source_type: str = ""
    snippet: str = ""
    full_text: str = ""
    metadata: SourceMetadata = Field(default_factory=SourceMetadata)


class QuestionAnswer(BaseModel):
    """Answer to a single evaluation question."""

    question: str
    answer: str = ""
    confidence: str = ""
    source_type_used: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


class RetrievalSummary(BaseModel):
    """Counts and status for the dual retrieval streams."""

    internet_sources_found: int = 0
    scientific_paper_sources_found: int = 0
    local_paper_database_enabled: bool = False


class TechnologyEvaluation(BaseModel):
    """Structured evaluation with flexible, question-driven answers."""

    technology: str = ""
    questions_file: str = ""
    executive_summary: str = ""
    answers: list[QuestionAnswer] = Field(default_factory=list)
    retrieval_summary: RetrievalSummary = Field(default_factory=RetrievalSummary)
