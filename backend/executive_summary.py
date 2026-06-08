"""Generate an executive summary from completed research answers."""

import os

from dotenv import load_dotenv
from openai import OpenAI

from schema import TechnologyEvaluation

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_MODEL = "gpt-4o-mini"
FALLBACK_SUMMARY = "Executive summary could not be generated."

SUMMARY_PROMPT = """Write a 3-5 paragraph executive summary for a cement/concrete decarbonization research report.

The summary must explain:
1. What the subject/technology is
2. Why it matters for cement/concrete decarbonization
3. Main environmental findings
4. Main economic or scalability findings
5. Major uncertainties or missing data

Use only the provided answers. Do not invent facts or numbers.
If information is missing, say so clearly.
Write in clear academic prose with paragraphs separated by blank lines.
Return plain text only — no markdown, no bullet lists, no JSON."""


def _format_answers_for_summary(evaluation: TechnologyEvaluation) -> str:
    lines: list[str] = []
    for item in evaluation.answers:
        lines.append(f"Q: {item.question}")
        lines.append(f"A: {item.answer}")
        lines.append(f"Confidence: {item.confidence or 'Low'}")
        lines.append("")
    return "\n".join(lines)


def generate_executive_summary(
    evaluation: TechnologyEvaluation,
    model: str = DEFAULT_MODEL,
) -> str:
    """Generate an executive summary using OpenAI, with a safe fallback."""
    if not OPENAI_API_KEY or OPENAI_API_KEY == "YOUR_OPENAI_TOKEN_HERE":
        return FALLBACK_SUMMARY

    client = OpenAI(api_key=OPENAI_API_KEY)
    user_content = (
        f"Subject: {evaluation.technology}\n"
        f"Question set: {evaluation.questions_file}\n\n"
        f"Answers:\n{_format_answers_for_summary(evaluation)}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
        )
        text = (response.choices[0].message.content or "").strip()
        return text or FALLBACK_SUMMARY
    except Exception:
        return FALLBACK_SUMMARY
