"""Tiered keyword relevance scoring for cement/concrete decarbonization papers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

RelevanceLabel = Literal["High", "Medium", "Low"]

# Tier 1 — strong decarbonization intent
TIER1_KEYWORDS: list[tuple[str, float]] = [
    ("decarbonization", 6.0),
    ("decarbonisation", 6.0),
    ("low-carbon", 5.5),
    ("low carbon", 5.5),
    ("net-zero", 5.0),
    ("net zero", 5.0),
    ("embodied carbon", 5.5),
    ("carbon footprint", 5.0),
    ("co2 reduction", 5.5),
    ("co₂ reduction", 5.5),
    ("greenhouse gas reduction", 5.5),
    ("emissions reduction", 5.0),
    ("carbon capture and storage", 6.0),
    ("carbon capture", 5.5),
    ("ccs", 4.0),
    ("ccus", 5.0),
    ("carbon utilization", 5.0),
    ("carbon utilisation", 5.0),
    ("carbon mineralization", 5.5),
    ("co2 mineralization", 5.5),
    ("co₂ mineralization", 5.5),
    ("carbonation curing", 5.0),
    ("carbonated concrete", 5.0),
    ("carbon sequestration", 5.0),
    ("cement kiln emissions", 5.5),
    ("clinker substitution", 5.0),
    ("clinker factor", 4.5),
    ("alternative fuel", 4.5),
    ("waste heat recovery", 4.5),
    ("energy efficiency in cement production", 5.0),
    ("emissions intensity", 5.0),
]

# Tier 2 — technology-specific decarbonization
TIER2_KEYWORDS: list[tuple[str, float]] = [
    ("supplementary cementitious material", 4.5),
    ("alternative supplementary cementitious material", 4.5),
    ("alternative cementitious material", 4.0),
    ("scm", 3.0),
    ("alternative scm", 4.0),
    ("fly ash replacement", 4.0),
    ("slag replacement", 4.0),
    ("calcined clay", 4.0),
    ("lc3", 4.0),
    ("limestone calcined clay cement", 4.5),
    ("natural pozzolan", 3.5),
    ("rice husk ash", 3.5),
    ("biomass ash", 3.5),
    ("recycled concrete fines", 3.5),
    ("geopolymer", 4.0),
    ("alkali-activated material", 4.0),
    ("alkali activated", 4.0),
    ("magnesium cement", 3.5),
    ("calcium sulfoaluminate cement", 3.5),
    ("csa cement", 3.0),
    ("belite cement", 3.5),
    ("recycled aggregate", 3.0),
    ("carbonated aggregate", 3.5),
    ("synthetic aggregate", 3.0),
    ("optimized mix design", 3.0),
    ("low cement concrete", 4.0),
    ("performance-based concrete design", 3.0),
    ("material efficiency", 3.5),
    ("structural optimization", 2.5),
    ("fly ash", 2.5),
    ("slag", 2.0),
]

# Tier 3 — general context (low weight)
TIER3_KEYWORDS: list[tuple[str, float]] = [
    ("portland cement", 1.0),
    ("cement", 0.8),
    ("concrete", 0.8),
    ("binder", 0.6),
    ("aggregate", 0.6),
    ("admixture", 0.6),
    ("mortar", 0.6),
    ("clinker", 1.0),
]

# Topics that reduce rank when decarbonization signal is weak
NEGATIVE_TOPICS: list[tuple[str, float]] = [
    ("corrosion", 2.5),
    ("fire resistance", 2.5),
    ("fire protection", 2.5),
    ("radiation shielding", 3.0),
    ("gamma scattering", 3.0),
    ("nuclear shielding", 3.0),
    ("water content measurement", 2.0),
    ("structural strengthening", 2.0),
    ("cyclic loading", 2.0),
    ("tunnel lining", 2.0),
    ("vertical shaft", 2.0),
    ("compressive strength", 1.5),
    ("durability", 1.5),
    ("curing regime", 1.5),
]

QUANT_SUSTAINABILITY_PATTERNS = [
    r"\d+\s*%",
    r"kg\s*co2e?",
    r"\bco2e\b",
    r"\bemissions?\b",
    r"\benergy\b",
    r"\bcost\b",
    r"\breduction\b",
    r"\breplacement\b",
    r"\bsubstitution\b",
]


@dataclass
class RelevanceResult:
    relevance_score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    matched_tier1_keywords: list[str] = field(default_factory=list)
    matched_tier2_keywords: list[str] = field(default_factory=list)
    matched_tier3_keywords: list[str] = field(default_factory=list)
    negative_topic_matches: list[str] = field(default_factory=list)
    relevance_label: RelevanceLabel = "Low"
    relevance_reason: str = ""
    has_quant_sustainability: bool = False
    strong_signal: bool = False


def _match_keywords(text: str, keywords: list[tuple[str, float]]) -> tuple[list[str], float]:
    matched: list[str] = []
    score = 0.0
    for keyword, weight in keywords:
        if keyword in text:
            matched.append(keyword)
            score += weight
    return matched, score


def _has_quant_sustainability(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in QUANT_SUSTAINABILITY_PATTERNS)


def score_relevance(text: str, *, query_terms: list[str] | None = None) -> RelevanceResult:
    """Score one paper's text against tiered decarbonization relevance signals."""
    normalized = text.lower()
    query_terms = [term.strip().lower() for term in (query_terms or []) if term.strip()]

    tier1, score1 = _match_keywords(normalized, TIER1_KEYWORDS)
    tier2, score2 = _match_keywords(normalized, TIER2_KEYWORDS)
    tier3, score3 = _match_keywords(normalized, TIER3_KEYWORDS)
    negatives, penalty = _match_keywords(normalized, NEGATIVE_TOPICS)

    query_bonus = 0.0
    query_matches: list[str] = []
    for term in query_terms:
        if term in normalized:
            query_bonus += 3.0
            query_matches.append(term)

    has_quant = _has_quant_sustainability(normalized)
    strong_signal = bool(tier1) or len(tier2) >= 2 or (bool(tier2) and has_quant)

    weak_signal = not tier1 and len(tier2) < 2 and not (tier2 and has_quant)
    negative_penalty = penalty if weak_signal else penalty * 0.35

    relevance_score = max(0.0, score1 + score2 + score3 + query_bonus - negative_penalty)

    label, reason = _classify_relevance(tier1, tier2, tier3, negatives, has_quant)

    all_matched = sorted(set(tier1 + tier2 + tier3 + query_matches))

    return RelevanceResult(
        relevance_score=round(relevance_score, 3),
        matched_keywords=all_matched,
        matched_tier1_keywords=sorted(set(tier1)),
        matched_tier2_keywords=sorted(set(tier2)),
        matched_tier3_keywords=sorted(set(tier3)),
        negative_topic_matches=sorted(set(negatives)),
        relevance_label=label,
        relevance_reason=reason,
        has_quant_sustainability=has_quant,
        strong_signal=strong_signal,
    )


def _classify_relevance(
    tier1: list[str],
    tier2: list[str],
    tier3: list[str],
    negatives: list[str],
    has_quant: bool,
) -> tuple[RelevanceLabel, str]:
    if tier1:
        sample = ", ".join(tier1[:3])
        return "High", f"Matched decarbonization terms: {sample}."

    if len(tier2) >= 2:
        sample = ", ".join(tier2[:3])
        return "High", f"Matched multiple technology-specific terms: {sample}."

    if tier2 and has_quant:
        return (
            "High",
            f"Matched {tier2[0]} with quantitative sustainability language.",
        )

    if tier2 and negatives and len(tier2) < 2:
        sample = ", ".join(negatives[:2])
        return (
            "Low",
            f"Matched {tier2[0]}, but mostly generic concrete topic terms ({sample}).",
        )

    if tier2:
        sample = ", ".join(tier2[:2])
        return (
            "Medium",
            f"Matched {sample}, but limited explicit decarbonization language.",
        )

    if negatives and not tier1 and not tier2:
        sample = ", ".join(negatives[:2])
        return (
            "Low",
            f"Mostly generic concrete topic terms ({sample}); low decarbonization signal.",
        )

    if tier3 and not tier1 and not tier2:
        return "Low", "Mostly generic concrete/cement terms; low decarbonization signal."

    return "Low", "Weak decarbonization relevance signal."


def passes_relevance_filter(result: RelevanceResult, *, min_score: float = 2.5) -> bool:
    """Require stronger evidence than generic cement/concrete mentions alone."""
    if result.strong_signal:
        return True
    if result.matched_tier1_keywords:
        return True
    if len(result.matched_tier2_keywords) >= 2:
        return True
    if result.matched_tier2_keywords and result.has_quant_sustainability:
        return True
    if (
        result.matched_tier3_keywords
        and not result.matched_tier1_keywords
        and not result.matched_tier2_keywords
    ):
        return False
    if (
        result.negative_topic_matches
        and not result.matched_tier1_keywords
        and len(result.matched_tier2_keywords) < 2
    ):
        return False
    return result.relevance_score >= min_score and bool(result.matched_tier2_keywords)
