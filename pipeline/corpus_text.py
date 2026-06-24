"""Text helpers for normalizing raw corpus records (no backend imports)."""


def stringify_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value[:50]:
            if isinstance(item, dict):
                for key in ("text", "title", "name", "value", "keyword"):
                    if key in item and item[key]:
                        parts.append(stringify_value(item[key]))
                        break
                else:
                    parts.append(stringify_value(item))
            else:
                parts.append(stringify_value(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        return " ".join(stringify_value(item) for item in value.values())
    return str(value)


def paragraph_text(record: dict, max_paragraphs: int = 5, max_chars: int = 4000) -> str:
    paragraphs = record.get("paragraphs") or []
    if not isinstance(paragraphs, list):
        return ""

    chunks: list[str] = []
    for paragraph in paragraphs[:max_paragraphs]:
        if isinstance(paragraph, dict):
            text = paragraph.get("text") or paragraph.get("content") or ""
            if text:
                chunks.append(str(text))
        elif paragraph:
            chunks.append(str(paragraph))

    combined = "\n".join(chunks)
    return combined[:max_chars]
