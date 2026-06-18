"""Stable source registry, citation normalization, and bibliography helpers."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SourceType = Literal["paper", "web"]


class RegisteredSource(BaseModel):
    source_id: str
    source_type: SourceType
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = "Not Reported"
    doi: str = ""
    journal_or_venue: str = ""
    url: str = ""
    abstract_or_snippet: str = ""
    original_index_in_corpus: int | None = None
    website_or_publisher: str = ""
    publication_date: str = ""
    retrieval_date: str = ""
    original_search_rank: int | None = None


class SourceBibliography(BaseModel):
    sources: list[RegisteredSource] = Field(default_factory=list)
    sources_used: list[RegisteredSource] = Field(default_factory=list)
    sources_considered: list[RegisteredSource] = Field(default_factory=list)
    citation_warnings: list[str] = Field(default_factory=list)


_CITATION_PATTERNS: list[tuple[re.Pattern[str], SourceType]] = [
    (re.compile(r"\bpaper[\s_-]?(\d+)\b", re.IGNORECASE), "paper"),
    (re.compile(r"\[p[\s_-]?(\d+)\]", re.IGNORECASE), "paper"),
    (re.compile(r"\bsource[\s_-]?(\d+)\b", re.IGNORECASE), "paper"),
    (re.compile(r"\bweb[\s_-]?(\d+)\b", re.IGNORECASE), "web"),
    (re.compile(r"\[web[\s_-]?(\d+)\]", re.IGNORECASE), "web"),
]

_STABLE_ID_PATTERN = re.compile(r"^(paper|web)_(\d{3,})$", re.IGNORECASE)


def stable_source_id(source_type: SourceType, index: int) -> str:
    prefix = "paper" if source_type == "paper" else "web"
    return f"{prefix}_{index:03d}"


def normalize_citation_token(token: str) -> str | None:
    """Map ambiguous citation labels to stable IDs when possible."""
    text = token.strip()
    if not text:
        return None

    stable_match = _STABLE_ID_PATTERN.match(text)
    if stable_match:
        prefix = stable_match.group(1).lower()
        number = int(stable_match.group(2))
        return stable_source_id("paper" if prefix == "paper" else "web", number)

    for pattern, source_type in _CITATION_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        number = int(match.groups()[-1])
        return stable_source_id(source_type, number)

    lowered = text.lower()
    if lowered.startswith("paper_") or lowered.startswith("web_"):
        prefix, _, suffix = lowered.partition("_")
        if suffix.isdigit():
            return stable_source_id("paper" if prefix == "paper" else "web", int(suffix))

    return None


def _stringify_authors(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


class SourceRegistry:
    """Registry of retrieved sources with stable IDs and bibliography helpers."""

    def __init__(self) -> None:
        self._sources: list[RegisteredSource] = []
        self._by_id: dict[str, RegisteredSource] = {}

    @property
    def sources(self) -> list[RegisteredSource]:
        return list(self._sources)

    def get(self, source_id: str) -> RegisteredSource | None:
        normalized = normalize_citation_token(source_id) or source_id
        return self._by_id.get(normalized)

    def register_standard_source(self, source: dict, *, search_rank: int | None = None) -> RegisteredSource:
        source_type_raw = str(source.get("source_type") or "").lower()
        source_type: SourceType = "web" if source_type_raw == "internet" else "paper"
        index = sum(1 for item in self._sources if item.source_type == source_type) + 1
        source_id = stable_source_id(source_type, index)

        metadata = source.get("metadata") or {}
        registered = RegisteredSource(
            source_id=source_id,
            source_type=source_type,
            title=str(source.get("title") or "Untitled source").strip(),
            authors=_stringify_authors(metadata.get("authors")),
            year=str(metadata.get("year") or "Not Reported").strip() or "Not Reported",
            doi=str(metadata.get("doi") or "").strip(),
            journal_or_venue=str(metadata.get("journal") or "").strip(),
            url=str(source.get("url") or "").strip(),
            abstract_or_snippet=str(source.get("snippet") or source.get("full_text") or "")[:1000],
            website_or_publisher=_website_from_url(str(source.get("url") or "")),
            retrieval_date=date.today().isoformat(),
            original_search_rank=search_rank,
        )
        self._sources.append(registered)
        self._by_id[source_id] = registered
        return registered

    def format_for_llm(self) -> str:
        if not self._sources:
            return "No sources available."

        sections: list[str] = [
            "Use only the SOURCE_ID values below when citing evidence.",
            "Do not invent source IDs. Do not cite sources that were not provided.",
        ]
        for source in self._sources:
            sections.append(_format_registered_source_for_llm(source))
        return "\n".join(sections)

    def normalize_text_citations(self, text: str) -> tuple[str, list[str]]:
        if not text:
            return text, []

        warnings: list[str] = []
        normalized = text

        def replace_match(match: re.Match[str]) -> str:
            raw = match.group(0)
            source_id = normalize_citation_token(raw)
            if source_id and source_id in self._by_id:
                return f"[{source_id}]"
            warnings.append(f"Unmatched source reference: {raw}")
            return "Unmatched source reference"

        for pattern, _ in _CITATION_PATTERNS:
            normalized = pattern.sub(replace_match, normalized)

        for source_id in re.findall(r"\b(?:paper|web)_\d{3}\b", normalized, flags=re.IGNORECASE):
            canonical = normalize_citation_token(source_id) or source_id
            if canonical not in self._by_id:
                warnings.append(f"Unmatched source reference: {source_id}")
                normalized = normalized.replace(source_id, "Unmatched source reference")

        return normalized, warnings

    def collect_cited_ids(self, payload: object) -> set[str]:
        cited: set[str] = set()
        skip_keys = {"relevant_sources", "sources", "sources_used", "sources_considered"}

        def walk(value: object, parent_key: str | None = None) -> None:
            if isinstance(value, dict):
                if parent_key == "source_provenance":
                    for ids in value.values():
                        if isinstance(ids, list):
                            for entry in ids:
                                if isinstance(entry, str):
                                    source_id = normalize_citation_token(entry) or entry
                                    if source_id in self._by_id:
                                        cited.add(source_id)
                    return
                for key, item in value.items():
                    if key in skip_keys:
                        continue
                    if key == "source_ids" and isinstance(item, list):
                        for entry in item:
                            if isinstance(entry, str):
                                source_id = normalize_citation_token(entry) or entry
                                if source_id in self._by_id:
                                    cited.add(source_id)
                        continue
                    walk(item, key)
            elif isinstance(value, list):
                for item in value:
                    walk(item, parent_key)
            elif isinstance(value, str):
                for token in re.findall(
                    r"\b(?:paper|web)[\s_-]?\d+\b|\[(?:paper|web)[\s_-]?\d+\]|"
                    r"\b(?:paper|web)_\d{3}\b",
                    value,
                    flags=re.IGNORECASE,
                ):
                    source_id = normalize_citation_token(token)
                    if source_id and source_id in self._by_id:
                        cited.add(source_id)

        walk(payload)
        return cited

    def attach_bibliography(self, payload: dict[str, Any]) -> SourceBibliography:
        warnings: list[str] = []
        cited_ids = self.collect_cited_ids(payload)

        for key in ("metrics", "companies", "pilot_demonstration_projects", "evidence_sources"):
            items = payload.get(key) or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                for field in ("source", "website_or_source", "url_or_reference", "source_id"):
                    if field not in item or not isinstance(item[field], str):
                        continue
                    normalized, field_warnings = self.normalize_text_citations(item[field])
                    item[field] = normalized
                    warnings.extend(field_warnings)
                    source_id = normalize_citation_token(normalized.strip("[]")) or normalize_citation_token(
                        item[field],
                    )
                    if source_id and source_id in self._by_id:
                        cited_ids.add(source_id)
                        if field == "source_id":
                            item["source_id"] = source_id

        evidence_sources = payload.get("evidence_sources") or []
        if isinstance(evidence_sources, list):
            enriched: list[dict[str, Any]] = []
            for item in evidence_sources:
                if not isinstance(item, dict):
                    continue
                enriched.append(self._enrich_evidence_source(item, cited_ids, warnings))
            payload["evidence_sources"] = enriched

        sources_used = [self._by_id[source_id] for source_id in sorted(cited_ids) if source_id in self._by_id]
        if not sources_used:
            sources_used = list(self._sources)

        used_ids = {source.source_id for source in sources_used}
        sources_considered = [
            source for source in self._sources if source.source_id not in used_ids
        ]

        if warnings:
            existing = payload.get("warnings") or []
            if not isinstance(existing, list):
                existing = []
            payload["warnings"] = existing + warnings

        return SourceBibliography(
            sources=self.sources,
            sources_used=sources_used,
            sources_considered=sources_considered,
            citation_warnings=sorted(set(warnings)),
        )

    def validate(self, payload: dict[str, Any]) -> list[str]:
        return self.collect_unmatched_references(payload)

    def collect_unmatched_references(self, payload: object) -> list[str]:
        warnings: list[str] = []

        def walk(value: object) -> None:
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str):
                if "Unmatched source reference" in value:
                    warnings.append(value)
                for pattern, _ in _CITATION_PATTERNS:
                    for match in pattern.finditer(value):
                        token = match.group(0)
                        source_id = normalize_citation_token(token)
                        if not source_id or source_id not in self._by_id:
                            warnings.append(f"Unmatched source reference: {token}")

        walk(payload)
        return sorted(set(warnings))

    def _enrich_evidence_source(
        self,
        item: dict[str, Any],
        cited_ids: set[str],
        warnings: list[str],
    ) -> dict[str, Any]:
        source_id = item.get("source_id")
        if isinstance(source_id, str):
            source_id = normalize_citation_token(source_id) or source_id
        else:
            source_id = None

        if not source_id:
            for candidate in (
                item.get("url_or_reference"),
                item.get("title"),
                item.get("source"),
            ):
                if not isinstance(candidate, str):
                    continue
                source_id = self._match_by_text(candidate)
                if source_id:
                    break

        if source_id and source_id in self._by_id:
            registered = self._by_id[source_id]
            cited_ids.add(source_id)
            return {
                **item,
                "source_id": source_id,
                "title": registered.title or item.get("title") or "Not Reported",
                "url_or_reference": registered.url or item.get("url_or_reference") or "",
                "source_type": registered.source_type,
                "snippet": registered.abstract_or_snippet or item.get("snippet") or "",
                "authors": registered.authors,
                "year": registered.year,
                "doi": registered.doi,
                "journal_or_venue": registered.journal_or_venue,
            }

        warnings.append(
            f"Unmatched evidence source: {item.get('title') or item.get('url_or_reference') or 'unknown'}",
        )
        return {
            **item,
            "source_id": source_id or "",
            "title": item.get("title") or "Source metadata unavailable",
        }

    def _match_by_text(self, text: str) -> str | None:
        lowered = text.strip().lower()
        if not lowered:
            return None
        source_id = normalize_citation_token(text)
        if source_id and source_id in self._by_id:
            return source_id
        for registered in self._sources:
            if registered.url and registered.url.lower() in lowered:
                return registered.source_id
            if registered.title and registered.title.lower() in lowered:
                return registered.source_id
            if registered.doi and registered.doi.lower() in lowered:
                return registered.source_id
        return None


def build_registry_from_sources(sources: list[dict]) -> SourceRegistry:
    registry = SourceRegistry()
    for rank, source in enumerate(sources, start=1):
        registry.register_standard_source(source, search_rank=rank)
    return registry


def format_source_citation_line(source: RegisteredSource) -> str:
    if source.source_type == "paper":
        authors = ", ".join(source.authors[:4]) if source.authors else "Authors not reported"
        venue = source.journal_or_venue or "Venue not reported"
        link = source.doi or source.url or "DOI/URL not reported"
        return (
            f"[{source.source_id}] {source.title}. {authors}. {source.year}. "
            f"{venue}. {link}."
        )
    link = source.url or "URL not reported"
    publisher = source.website_or_publisher or "Publisher not reported"
    retrieved = source.retrieval_date or "Retrieval date not reported"
    return (
        f"[{source.source_id}] {source.title}. {publisher}. {link}. "
        f"Retrieved {retrieved}."
    )


def _format_registered_source_for_llm(source: RegisteredSource) -> str:
    lines = [
        f"SOURCE_ID: {source.source_id}",
        f"SOURCE_TYPE: {source.source_type}",
        f"TITLE: {source.title}",
    ]
    if source.source_type == "paper":
        lines.extend(
            [
                f"AUTHORS: {', '.join(source.authors) if source.authors else 'Not Reported'}",
                f"YEAR: {source.year}",
                f"DOI: {source.doi or 'Not Reported'}",
                f"JOURNAL: {source.journal_or_venue or 'Not Reported'}",
                f"URL: {source.url or 'Not Reported'}",
            ],
        )
    else:
        lines.extend(
            [
                f"URL: {source.url or 'Not Reported'}",
                f"WEBSITE: {source.website_or_publisher or 'Not Reported'}",
                f"PUBLICATION_DATE: {source.publication_date or 'Not Reported'}",
                f"RETRIEVAL_DATE: {source.retrieval_date or 'Not Reported'}",
            ],
        )
    lines.append(f"SNIPPET: {source.abstract_or_snippet or 'Not Reported'}")
    return "\n".join(lines)


def _website_from_url(url: str) -> str:
    if not url:
        return ""
    match = re.match(r"https?://([^/]+)", url)
    return match.group(1) if match else ""


def registry_from_technology_record(record: dict[str, Any]) -> SourceRegistry:
    """Build a registry from prepared database record source metadata."""
    registry = SourceRegistry()
    relevant_sources = record.get("relevant_sources") or []
    if not isinstance(relevant_sources, list):
        return registry

    paper_count = 0
    web_count = 0
    for item in relevant_sources:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("source_id") or item.get("paper_id") or "").strip()
        url = str(item.get("url") or "").strip()
        source_type: SourceType = "web" if url and not item.get("doi") else "paper"
        if raw_id.startswith("web_"):
            source_type = "web"
        elif raw_id.startswith("paper_"):
            source_type = "paper"

        if raw_id and _STABLE_ID_PATTERN.match(raw_id):
            source_id = raw_id
        elif source_type == "paper":
            paper_count += 1
            source_id = stable_source_id("paper", paper_count)
        else:
            web_count += 1
            source_id = stable_source_id("web", web_count)

        registered = RegisteredSource(
            source_id=source_id,
            source_type=source_type,
            title=str(item.get("title") or "").strip(),
            authors=_stringify_authors(item.get("authors")),
            year=str(item.get("year") or "Not Reported"),
            doi=str(item.get("doi") or "").strip(),
            journal_or_venue=str(item.get("journal_or_venue") or item.get("journal") or "").strip(),
            url=url,
            abstract_or_snippet=str(item.get("snippet") or item.get("abstract") or "")[:1000],
            website_or_publisher=str(item.get("website_or_publisher") or _website_from_url(url)),
            retrieval_date=str(item.get("retrieval_date") or date.today().isoformat()),
        )
        registry._sources.append(registered)
        registry._by_id[source_id] = registered
    return registry


def attach_record_bibliography(record: dict[str, Any]) -> dict[str, Any]:
    registry = registry_from_technology_record(record)
    payload = dict(record)
    bibliography = registry.attach_bibliography(payload)
    payload["sources"] = [source.model_dump() for source in bibliography.sources]
    payload["sources_used"] = [source.model_dump() for source in bibliography.sources_used]
    payload["sources_considered"] = [
        source.model_dump() for source in bibliography.sources_considered
    ]
    payload["citation_warnings"] = bibliography.citation_warnings
    issues = registry.validate(payload)
    if issues:
        logger.warning(
            "Citation validation issues for %s: %s",
            record.get("record_id"),
            issues,
        )
        payload["citation_warnings"] = sorted(set(payload["citation_warnings"] + issues))
    return payload
