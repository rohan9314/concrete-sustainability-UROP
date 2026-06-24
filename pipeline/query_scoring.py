"""Query-aware scoring and CCS technology synonym expansion."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CCS_TECHNOLOGY_SYNONYMS: dict[str, list[str]] = {
    "chemical absorption": [
        "chemical absorption",
        "absorption",
        "amine",
        "amine scrubbing",
        "solvent",
        "solvent-based capture",
        "post-combustion capture",
        "mea",
        "monoethanolamine",
    ],
    "cryogenic processes": [
        "cryogenic",
        "cryogenic carbon capture",
        "low temperature separation",
        "liquefaction",
        "co2 liquefaction",
        "phase separation",
    ],
    "oxy-fuel combustion": [
        "oxy-fuel",
        "oxyfuel",
        "oxy-fuel combustion",
        "oxygen combustion",
        "oxygen-enriched combustion",
        "flue gas recycle",
        "high co2 flue gas",
    ],
    "membrane separation": [
        "membrane separation",
        "membrane",
        "co2 membrane",
        "gas separation membrane",
        "polymeric membrane",
        "ceramic membrane",
        "facilitated transport membrane",
    ],
    "calcium looping": [
        "calcium looping",
        "cal",
        "calcium oxide",
        "cao",
        "calcium carbonate",
        "caco3",
        "calcination",
        "carbonation",
        "sorbent looping",
        "carbonate looping",
    ],
    "direct separation": [
        "direct separation",
        "direct separation calciner",
        "indirectly heated calciner",
        "leilac",
        "low emissions intensity lime and cement",
        "separated calcination",
        "calcination co2 capture",
    ],
}

TARGET_TECHNOLOGIES: list[tuple[str, str]] = [
    ("chemical absorption", "chemical_absorption"),
    ("cryogenic processes", "cryogenic_processes"),
    ("oxy-fuel combustion", "oxy_fuel_combustion"),
    ("membrane separation", "membrane_separation"),
    ("calcium looping", "calcium_looping"),
    ("direct separation", "direct_separation"),
]

_SHORT_TOKEN_PATTERN = re.compile(r"^[a-z0-9]{1,4}$")
_QUERY_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass
class QueryContext:
    query: str = ""
    technology_name: str = ""
    query_terms: list[str] = field(default_factory=list)
    match_phrases: list[tuple[str, float, str]] = field(default_factory=list)


@dataclass
class QueryScoreResult:
    query_score: float = 0.0
    query_matches: list[str] = field(default_factory=list)
    technology_synonym_matches: list[str] = field(default_factory=list)
    strong_query_match: bool = False
    moderate_query_match: bool = False


def normalize_technology_name(name: str) -> str | None:
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    if not normalized:
        return None
    if normalized in CCS_TECHNOLOGY_SYNONYMS:
        return normalized
    aliases = {
        "oxy fuel combustion": "oxy-fuel combustion",
        "oxyfuel combustion": "oxy-fuel combustion",
        "cryogenic process": "cryogenic processes",
    }
    return aliases.get(normalized)


def tokenize_query(query: str) -> list[str]:
    return _tokenize_query(query)


def _tokenize_query(query: str) -> list[str]:
    return [
        token
        for token in _QUERY_TOKEN_PATTERN.findall(query.lower())
        if len(token) > 2
    ]


def _phrase_weight(phrase: str, *, source: str) -> float:
    if " " in phrase:
        return 5.0 if source == "synonym" else 4.0
    if _SHORT_TOKEN_PATTERN.match(phrase):
        return 3.5 if source == "synonym" else 2.5
    return 4.0 if source == "synonym" else 3.0


def _match_phrase(text: str, phrase: str) -> bool:
    phrase = phrase.lower().strip()
    if not phrase:
        return False
    if _SHORT_TOKEN_PATTERN.match(phrase):
        return re.search(rf"\b{re.escape(phrase)}\b", text, flags=re.IGNORECASE) is not None
    return phrase in text


def build_query_context(*, query: str = "", technology_name: str = "") -> QueryContext:
    """Build phrase lists from an optional query and/or named CCS technology."""
    query = query.strip()
    normalized_tech = normalize_technology_name(technology_name)
    technology_name = normalized_tech or technology_name.strip()

    query_terms = _tokenize_query(query)
    phrases: dict[str, tuple[float, str]] = {}

    def add_phrase(phrase: str, source: str) -> None:
        phrase = phrase.lower().strip()
        if not phrase:
            return
        weight = _phrase_weight(phrase, source=source)
        existing = phrases.get(phrase)
        if existing is None or weight > existing[0]:
            phrases[phrase] = (weight, source)

    if normalized_tech:
        for synonym in CCS_TECHNOLOGY_SYNONYMS[normalized_tech]:
            add_phrase(synonym, "synonym")

    if query:
        query_lower = query.lower()
        for token in query_terms:
            add_phrase(token, "query")

        words = query_lower.split()
        for index in range(len(words) - 1):
            add_phrase(f"{words[index]} {words[index + 1]}", "query")

        for phrase in list(phrases):
            if phrase in query_lower and phrases[phrase][1] == "synonym":
                weight, _ = phrases[phrase]
                phrases[phrase] = (max(weight, 5.5), "synonym")

    match_phrases = sorted(
        ((phrase, weight, source) for phrase, (weight, source) in phrases.items()),
        key=lambda item: (-len(item[0]), item[0]),
    )
    return QueryContext(
        query=query,
        technology_name=technology_name,
        query_terms=query_terms,
        match_phrases=match_phrases,
    )


def score_query(text: str, context: QueryContext | None) -> QueryScoreResult:
    """Score text against query terms and technology synonyms."""
    if context is None or (not context.query and not context.technology_name):
        return QueryScoreResult()

    normalized = text.lower()
    query_matches: list[str] = []
    synonym_matches: list[str] = []
    score = 0.0

    for phrase, weight, source in context.match_phrases:
        if not _match_phrase(normalized, phrase):
            continue
        score += weight
        if source == "synonym":
            synonym_matches.append(phrase)
        else:
            query_matches.append(phrase)

    query_score = round(score, 3)
    return QueryScoreResult(
        query_score=query_score,
        query_matches=sorted(set(query_matches)),
        technology_synonym_matches=sorted(set(synonym_matches)),
        strong_query_match=query_score >= 8.0 or len(synonym_matches) >= 2 or len(query_matches) >= 3,
        moderate_query_match=query_score >= 4.0 or bool(query_matches or synonym_matches),
    )


def has_active_query(context: QueryContext | None) -> bool:
    return context is not None and bool(context.query or context.technology_name)
