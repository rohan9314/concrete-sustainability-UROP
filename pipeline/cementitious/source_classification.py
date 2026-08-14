"""Deterministic web/literature source-type classification.

Maps domains and metadata onto ``schema.WEB_SOURCE_TYPES`` using explicit
precedence so academic publishers, trade magazines, and encyclopedias are
never collapsed into ``Company Website``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pipeline.cementitious.schema import WEB_SOURCE_TYPES

# Canonical labels used by this pipeline (subset/aliases of WEB_SOURCE_TYPES).
SOURCE_TYPE_ACADEMIC_LITERATURE = "Academic Literature"
SOURCE_TYPE_GOVERNMENT = "Government Website"
SOURCE_TYPE_ACADEMIC_INSTITUTION = "Academic Institution"
SOURCE_TYPE_STANDARDS = "Standards Organization"
SOURCE_TYPE_INDUSTRY_ASSOCIATION = "Industry Association"
SOURCE_TYPE_NEWS = "News"
SOURCE_TYPE_CONFERENCE = "Conference or Project Website"
SOURCE_TYPE_TECHNICAL_REPORT = "Technical Report"
SOURCE_TYPE_OTHER = "Other Web Source"
SOURCE_TYPE_COMPANY = "Company Website"

# Lower number = more authoritative. Used only to prefer URLs when a cap binds;
# it never drops a source by itself.
SOURCE_AUTHORITY_RANK: dict[str, int] = {
    SOURCE_TYPE_ACADEMIC_LITERATURE: 1,
    SOURCE_TYPE_GOVERNMENT: 2,
    SOURCE_TYPE_ACADEMIC_INSTITUTION: 2,
    SOURCE_TYPE_TECHNICAL_REPORT: 2,
    SOURCE_TYPE_STANDARDS: 3,
    SOURCE_TYPE_INDUSTRY_ASSOCIATION: 4,
    SOURCE_TYPE_COMPANY: 5,
    SOURCE_TYPE_CONFERENCE: 5,
    SOURCE_TYPE_NEWS: 6,
    SOURCE_TYPE_OTHER: 7,
}


def authority_rank_for_source_type(source_type: str) -> int:
    """1 = peer-reviewed literature … 7 = other. Unknown labels rank as other."""
    return int(SOURCE_AUTHORITY_RANK.get(source_type, 7))


CLASSIFICATION_METHODS = (
    "explicit_metadata",
    "domain_rule",
    "url_rule",
    "page_metadata",
    "content_heuristic",
    "llm_fallback",
    "unknown",
)

# Domain / host suffixes → canonical WEB_SOURCE_TYPES label.
# Longer / more specific hosts are matched before shorter suffixes.
_ACADEMIC_PUBLISHER_HOSTS: tuple[str, ...] = (
    "mdpi.com",
    "sciencedirect.com",
    "link.springer.com",
    "springer.com",
    "onlinelibrary.wiley.com",
    "wiley.com",
    "tandfonline.com",
    "nature.com",
    "pubs.rsc.org",
    "rsc.org",
    "pubs.acs.org",
    "acs.org",
    "frontiersin.org",
    "scielo.org",
    "ieee.org",
    "acm.org",
    "plos.org",
    "hindawi.com",
    "elsevier.com",
    "sagepub.com",
    "oup.com",
    "cambridge.org",
)

_IGO_OR_TECHNICAL_REPORT_HOSTS: tuple[str, ...] = (
    "ieaghg.org",
    "iea.org",
    "worldbank.org",
    "oecd.org",
    "un.org",
    "unece.org",
    "ipcc.ch",
    "irena.org",
)

_NGO_REPORT_HOSTS: tuple[str, ...] = (
    "catf.us",
    "cdn.catf.us",
    "wri.org",
    "nrdc.org",
    "edf.org",
    "climateworks.org",
)

_TRADE_PUBLICATION_HOSTS: tuple[str, ...] = (
    "zkg.de",
    "worldcement.com",
    "cemnet.com",
    "globalcement.com",
    "concreteconstruction.net",
)

_INDUSTRY_ASSOCIATION_HOSTS: tuple[str, ...] = (
    "cement.org",
    "gccassociation.org",
    "gcca.org",
    "cembureau.eu",
    "pca.org",
)

_ENCYCLOPEDIA_HOSTS: tuple[str, ...] = (
    "wikipedia.org",
    "wikimedia.org",
    "britannica.com",
)

_GOVERNMENT_HOST_MARKERS: tuple[str, ...] = (
    "energy.gov",
    "epa.gov",
    "nist.gov",
    "doe.gov",
    "ornl.gov",
    "nrel.gov",
    "pnnl.gov",
    "lbl.gov",
    "llnl.gov",
    "sandia.gov",
)

_REPOSITORY_HOST_MARKERS: tuple[str, ...] = (
    "collectionscanada.gc.ca",
    "bac-lac.gc.ca",
    "archives.gov",
    "hdl.handle.net",
    "zenodo.org",
    "figshare.com",
    "arxiv.org",
    "ssrn.com",
    "researchgate.net",
)

_STANDARDS_HOSTS: tuple[str, ...] = (
    "astm.org",
    "iso.org",
    "bsigroup.com",
    "en-standard.eu",
)

# Map free-text / legacy labels onto WEB_SOURCE_TYPES.
_EXPLICIT_ALIASES: dict[str, str] = {
    "literature": SOURCE_TYPE_ACADEMIC_LITERATURE,
    "academic literature": SOURCE_TYPE_ACADEMIC_LITERATURE,
    "journal": SOURCE_TYPE_ACADEMIC_LITERATURE,
    "academic journal": SOURCE_TYPE_ACADEMIC_LITERATURE,
    "academic publisher": SOURCE_TYPE_ACADEMIC_LITERATURE,
    "government": SOURCE_TYPE_GOVERNMENT,
    "government website": SOURCE_TYPE_GOVERNMENT,
    "intergovernmental": SOURCE_TYPE_TECHNICAL_REPORT,
    "intergovernmental organization": SOURCE_TYPE_TECHNICAL_REPORT,
    "technical report": SOURCE_TYPE_TECHNICAL_REPORT,
    "ngo": SOURCE_TYPE_TECHNICAL_REPORT,
    "nonprofit": SOURCE_TYPE_TECHNICAL_REPORT,
    "ngo or nonprofit report": SOURCE_TYPE_TECHNICAL_REPORT,
    "trade publication": SOURCE_TYPE_TECHNICAL_REPORT,
    "technical magazine": SOURCE_TYPE_TECHNICAL_REPORT,
    "industry association": SOURCE_TYPE_INDUSTRY_ASSOCIATION,
    "company": SOURCE_TYPE_COMPANY,
    "company website": SOURCE_TYPE_COMPANY,
    "university": SOURCE_TYPE_ACADEMIC_INSTITUTION,
    "academic institution": SOURCE_TYPE_ACADEMIC_INSTITUTION,
    "institutional repository": SOURCE_TYPE_ACADEMIC_INSTITUTION,
    "thesis": SOURCE_TYPE_ACADEMIC_INSTITUTION,
    "dissertation": SOURCE_TYPE_ACADEMIC_INSTITUTION,
    "encyclopedia": SOURCE_TYPE_OTHER,
    "general reference": SOURCE_TYPE_OTHER,
    "other web source": SOURCE_TYPE_OTHER,
    "news": SOURCE_TYPE_NEWS,
    "standards organization": SOURCE_TYPE_STANDARDS,
    "conference or project website": SOURCE_TYPE_CONFERENCE,
}


@dataclass(frozen=True)
class SourceClassification:
    """Result of deterministic source-type classification."""

    source_type: str
    method: str
    reason: str
    matched_rule: str = ""

    @property
    def authority_rank(self) -> int:
        return authority_rank_for_source_type(self.source_type)

    def as_dict(self) -> dict[str, str]:
        return {
            "source_type": self.source_type,
            "classification_method": self.method,
            "classification_reason": self.reason,
            "matched_rule": self.matched_rule,
            "authority_rank": str(self.authority_rank),
        }


def _host_from_url(url: str, domain: str = "") -> str:
    host = (domain or "").strip().lower()
    if host.startswith("www."):
        host = host[4:]
    if host:
        return host
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _host_matches(host: str, rule: str) -> bool:
    rule = rule.lower().lstrip(".")
    if not host or not rule:
        return False
    return host == rule or host.endswith("." + rule)


def _match_host_list(host: str, rules: tuple[str, ...]) -> str | None:
    for rule in sorted(rules, key=len, reverse=True):
        if _host_matches(host, rule):
            return rule
    return None


def normalize_source_type_label(value: str) -> str | None:
    """Map an explicit label onto WEB_SOURCE_TYPES, or None if unknown."""
    text = (value or "").strip()
    if not text:
        return None
    if text in WEB_SOURCE_TYPES:
        return text
    return _EXPLICIT_ALIASES.get(text.casefold())


def classify_source_type(
    *,
    url: str = "",
    title: str = "",
    domain: str = "",
    explicit_source_type: str = "",
    raw_source_type: str = "",
    page_text: str = "",
) -> SourceClassification:
    """
    Classify a source into ``WEB_SOURCE_TYPES`` with deterministic precedence.

    Order:
      1. Explicit metadata already on the source
      2. Domain / URL heuristics
      3. Page title / content heuristics
      4. Unknown fallback (never crashes)
    """
    for label, method in (
        (explicit_source_type, "explicit_metadata"),
        (raw_source_type, "explicit_metadata"),
    ):
        mapped = normalize_source_type_label(label)
        if mapped:
            return SourceClassification(
                source_type=mapped,
                method=method,
                reason=f"explicit label {label!r} → {mapped}",
                matched_rule=label.strip(),
            )

    host = _host_from_url(url, domain)
    url_l = (url or "").casefold()
    title_l = (title or "").casefold()
    blob = f"{url_l} {title_l} {host}"

    # --- Domain rules (strongest structural signal) ---
    matched = _match_host_list(host, _ENCYCLOPEDIA_HOSTS)
    if matched:
        return SourceClassification(
            SOURCE_TYPE_OTHER,
            "domain_rule",
            "encyclopedia / general reference host",
            matched,
        )

    matched = _match_host_list(host, _ACADEMIC_PUBLISHER_HOSTS)
    if matched:
        return SourceClassification(
            SOURCE_TYPE_ACADEMIC_LITERATURE,
            "domain_rule",
            "academic publisher / journal host",
            matched,
        )

    if host.endswith(".gov") or _match_host_list(host, _GOVERNMENT_HOST_MARKERS):
        rule = _match_host_list(host, _GOVERNMENT_HOST_MARKERS) or host
        return SourceClassification(
            SOURCE_TYPE_GOVERNMENT,
            "domain_rule",
            "government host",
            rule,
        )

    matched = _match_host_list(host, _IGO_OR_TECHNICAL_REPORT_HOSTS)
    if matched:
        return SourceClassification(
            SOURCE_TYPE_TECHNICAL_REPORT,
            "domain_rule",
            "intergovernmental / major technical-report organization",
            matched,
        )

    matched = _match_host_list(host, _NGO_REPORT_HOSTS)
    if matched:
        return SourceClassification(
            SOURCE_TYPE_TECHNICAL_REPORT,
            "domain_rule",
            "NGO / nonprofit report host (mapped to Technical Report)",
            matched,
        )

    matched = _match_host_list(host, _TRADE_PUBLICATION_HOSTS)
    if matched:
        # No dedicated trade-magazine label in WEB_SOURCE_TYPES; Technical Report
        # is the closest controlled value for industry technical publications.
        return SourceClassification(
            SOURCE_TYPE_TECHNICAL_REPORT,
            "domain_rule",
            "trade / technical publication host (mapped to Technical Report)",
            matched,
        )

    matched = _match_host_list(host, _INDUSTRY_ASSOCIATION_HOSTS)
    if matched or "gcca" in host:
        return SourceClassification(
            SOURCE_TYPE_INDUSTRY_ASSOCIATION,
            "domain_rule",
            "industry association host",
            matched or host,
        )

    matched = _match_host_list(host, _STANDARDS_HOSTS)
    if matched:
        return SourceClassification(
            SOURCE_TYPE_STANDARDS,
            "domain_rule",
            "standards organization host",
            matched,
        )

    matched = _match_host_list(host, _REPOSITORY_HOST_MARKERS)
    if matched or host.endswith(".edu") or host.endswith(".ac.uk") or ".ac." in host:
        rule = matched or host
        return SourceClassification(
            SOURCE_TYPE_ACADEMIC_INSTITUTION,
            "domain_rule",
            "university / institutional repository host",
            rule,
        )

    # --- URL path rules ---
    if any(x in url_l for x in ("/thesis", "/dissertation", "/etd/", "/handle/")):
        return SourceClassification(
            SOURCE_TYPE_ACADEMIC_INSTITUTION,
            "url_rule",
            "URL path indicates thesis / institutional handle",
            "thesis_or_handle_path",
        )

    # --- Title / content heuristics (still before company fallback) ---
    page_l = (page_text or "")[:4000].casefold()
    combined = f"{blob} {page_l}"
    if any(x in combined for x in ("reuters", "bloomberg", "/news/", "press release")):
        return SourceClassification(
            SOURCE_TYPE_NEWS,
            "content_heuristic",
            "news / press markers in title or URL",
            "news_markers",
        )
    if any(x in combined for x in ("conference", "symposium", "workshop")):
        return SourceClassification(
            SOURCE_TYPE_CONFERENCE,
            "content_heuristic",
            "conference / project markers",
            "conference_markers",
        )
    if any(x in title_l for x in ("white paper", "whitepaper", "technical report", "working paper")):
        return SourceClassification(
            SOURCE_TYPE_TECHNICAL_REPORT,
            "page_metadata",
            "title indicates technical report",
            "report_title",
        )
    if any(x in title_l for x in ("journal", "vol.", "doi:", "issn")):
        return SourceClassification(
            SOURCE_TYPE_ACADEMIC_LITERATURE,
            "page_metadata",
            "title indicates academic journal article",
            "journal_title",
        )

    # PDF on an unclassified host: prefer Technical Report over Company Website
    if url_l.rstrip("/").endswith(".pdf") or ".pdf?" in url_l:
        return SourceClassification(
            SOURCE_TYPE_TECHNICAL_REPORT,
            "url_rule",
            "PDF URL without a stronger domain class",
            "pdf_url",
        )

    # Company only when no stronger rule matched
    if any(x in blob for x in (" company", "corp", "inc.", "ltd", "gmbh", "solutions")):
        return SourceClassification(
            SOURCE_TYPE_COMPANY,
            "content_heuristic",
            "commercial markers without a stronger source class",
            "commercial_markers",
        )

    if host and not host.endswith((".edu", ".gov", ".ac.uk")):
        # Remaining commercial / organizational sites default to company only
        # when the host looks like a private org — never override publishers above.
        return SourceClassification(
            SOURCE_TYPE_COMPANY,
            "domain_rule",
            "default company website after stronger rules failed",
            host,
        )

    return SourceClassification(
        SOURCE_TYPE_OTHER,
        "unknown",
        "no matching rule",
        "",
    )


def guess_source_type(url: str, title: str = "", domain: str = "") -> str:
    """Backward-compatible wrapper returning only the canonical source type."""
    return classify_source_type(url=url, title=title, domain=domain).source_type


def classify_source_type_with_meta(
    *,
    url: str = "",
    title: str = "",
    domain: str = "",
    explicit_source_type: str = "",
    raw_source_type: str = "",
    page_text: str = "",
) -> dict[str, Any]:
    """Return classification plus audit fields for screening/extract metadata."""
    result = classify_source_type(
        url=url,
        title=title,
        domain=domain,
        explicit_source_type=explicit_source_type,
        raw_source_type=raw_source_type,
        page_text=page_text,
    )
    return result.as_dict()
