"""Prompt templates for carbon capture 26-question extraction."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are a research analyst specializing in cement and concrete decarbonization technologies.

Your task is to extract factual information from scientific paper sources and answer the evaluation questions provided.

Focus on the specified carbon capture methodology. Do not answer as if the technology is generic carbon capture.
Every answer must be specific to the methodology context provided.

STRICT RULES:
1. Return valid JSON only — no markdown, no commentary, no code fences.
2. Never invent or estimate numerical values. If a number is not explicitly stated in the sources, use "Not Found".
3. Every numerical claim in your answers must be traceable to a specific source URL listed in that answer's sources array.
4. Use "Not Found" when information is unavailable in the provided sources.
5. Provide exactly one answer object for each evaluation question, in the same order as the questions list.
6. Assign a confidence level (High, Medium, or Low) for each answer.
7. Set source_type_used to ["scientific_paper"] for paper-only extraction.
8. Scientific papers may contain peer-reviewed evidence — prioritize them for technical and quantitative claims.
9. Do not extrapolate, infer numbers, or fill gaps with general industry knowledge.
10. Write substantive answers of 2-5 sentences when sources contain relevant information."""


def build_extraction_prompt(
    *,
    technology_name: str,
    methodology_name: str,
    methodology_subcategory: str,
    source_content: str,
    questions: list[str],
) -> str:
    numbered_questions = "\n".join(
        f"{i}. {question}" for i, question in enumerate(questions, start=1)
    )
    answer_blocks = ",\n".join(
        f"""    {{
      "question": {json.dumps(question, ensure_ascii=False)},
      "answer": "",
      "confidence": "",
      "source_type_used": [],
      "sources": []
    }}"""
        for question in questions
    )

    return f"""Analyze the following scientific paper about: "{technology_name}"

Carbon capture methodology context:
- Methodology: {methodology_name}
- Subcategory: {methodology_subcategory}
- Category: Carbon Capture (decarbonization levers taxonomy)

Answer each evaluation question using only the provided source. When the paper discusses
this specific capture approach, extract details for that methodology. If the paper is not
about this methodology, answer "Not Found" for methodology-specific questions.

QUESTIONS:
{numbered_questions}

For each answer:
- Set "question" to the exact question text from the list above.
- Set "answer" to a substantive 2-5 sentence summary, or "Not Found".
- Set "confidence" to High, Medium, or Low.
- Set "source_type_used" to ["scientific_paper"] when the paper informs the answer.
- Populate "sources" with every source used for that answer, including title, url, source_type,
  snippet, full_text when available, and metadata (authors array, year string, journal, doi).

SOURCE DOCUMENT:
{source_content}

Return a single JSON object:
{{
  "technology": "{technology_name}",
  "answers": [
{answer_blocks}
  ]
}}"""
