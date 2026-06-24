"""Small corpus record helpers shared by pipeline stages."""


def record_dedupe_key(record: dict) -> str:
    """Stable identifier for deduplicating pickle records."""
    doi = str(record.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"

    url = str(record.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"

    title = str(record.get("title") or "").strip().lower()
    return f"title:{title}" if title else ""
