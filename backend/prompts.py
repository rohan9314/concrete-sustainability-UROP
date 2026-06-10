"""System and extraction prompts for OpenAI structured information extraction."""

import json

SYSTEM_PROMPT = """You are a research analyst specializing in cement and concrete decarbonization technologies.

Your task is to extract factual information from two types of source documents and answer the evaluation questions provided:

1. INTERNET sources (source_type: "internet")
   - Startup websites, company white papers, EPDs, technical reports, government reports, news, and deployment announcements
   - Answer: "What is being claimed publicly?"

2. SCIENTIFIC PAPER sources (source_type: "scientific_paper")
   - Peer-reviewed papers from the local cement/concrete paper database
   - Abstracts, metadata, and cited scientific evidence from the provided paper dataset
   - Answer: "What evidence exists in the scientific literature?"

STRICT RULES:
1. Return valid JSON only — no markdown, no commentary, no code fences.
2. Never invent or estimate numerical values. If a number is not explicitly stated in the sources, use "Not Found".
3. Every numerical claim in your answers must be traceable to a specific source URL listed in that answer's sources array.
4. Use "Not Found" when information is unavailable in the provided sources.
5. Provide exactly one answer object for each evaluation question, in the same order as the questions list.
6. Assign a confidence level (High, Medium, or Low) for each answer.
7. Set source_type_used to the list of source types that informed the answer (e.g. ["internet"], ["scientific_paper"], or ["internet", "scientific_paper"]).
8. Compare internet claims with scientific literature when both are available.
9. If company/internet claims disagree with scientific literature, explicitly mention the disagreement in the answer and lower the confidence level.
10. Scientific papers may contain peer-reviewed evidence, experimental results, cost estimates, energy estimates, emissions estimates, and lifecycle analysis — prioritize them for technical and quantitative claims.
11. Internet sources may contain company claims, deployment claims, market data, EPDs, and startup information — use them to capture public positioning and commercial status.
12. Do not extrapolate, infer numbers, or fill gaps with general industry knowledge.
13. All string field values must be plain strings.
14. Write substantive answers of 2-5 sentences when sources contain relevant information. Synthesize across multiple sources where appropriate.
15. Use "Not Found" only when the provided sources contain no relevant discussion of the question topic.
16. When exact numbers are unavailable but sources discuss a topic qualitatively (e.g., barriers, energy types, deployment status, infrastructure needs), summarize what the sources state without inventing figures."""


def build_extraction_prompt(
    technology_name: str,
    source_content: str,
    questions: list[str],
    internet_count: int = 0,
    paper_count: int = 0,
) -> str:
    """Build the user extraction prompt from technology name, sources, and questions."""
    numbered_questions = "\n".join(
        f"{i}. {question}" for i, question in enumerate(questions, start=1)
    )
    answer_blocks = ",\n".join(
        f"""    {{
      "question": {json_escape(question)},
      "answer": "",
      "confidence": "",
      "source_type_used": [],
      "sources": []
    }}"""
        for question in questions
    )

    return f"""Analyze the following source documents about the technology: "{technology_name}"

You have {internet_count} internet source(s) and {paper_count} scientific paper source(s).

Answer each of these {len(questions)} evaluation questions using only the provided sources:

{numbered_questions}

For each answer:
- Set "question" to the exact question text from the list above.
- Set "answer" to a substantive 2-5 sentence summary of extracted information, or "Not Found" if the sources contain no relevant discussion of the topic.
- Set "confidence" to High, Medium, or Low. Lower confidence when internet and scientific sources disagree.
- Set "source_type_used" to the source types consulted (["internet"], ["scientific_paper"], or both).
- Populate "sources" with every source used for that answer. For each source include:
  - title, url, and source_type — must be exactly "internet" or "scientific_paper"
  - snippet and full_text when available
  - metadata for scientific papers:
    - authors: JSON array of strings (e.g. ["Smith, J.", "Doe, A."]), never a single string
    - year: string (e.g. "2022"), never a number
    - journal and doi: strings, or "" if unknown

When both source types are available, compare public/internet claims against peer-reviewed scientific evidence.
If they conflict, state the disagreement clearly in the answer.

SOURCE DOCUMENTS:
{source_content}

Return a single JSON object matching this exact schema:
{{
  "technology": "{technology_name}",
  "answers": [
{answer_blocks}
  ]
}}"""


def json_escape(value: str) -> str:
    """Return a JSON-encoded string literal for embedding in prompt templates."""
    return json.dumps(value, ensure_ascii=False)
