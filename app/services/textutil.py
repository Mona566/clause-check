import re


def normalize_ws(text: str) -> str:
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    return re.sub(r"\s+", " ", text).strip()


def quote_in_source(quote: str | None, source: str) -> bool:
    if not quote or not quote.strip():
        return False
    return normalize_ws(quote) in normalize_ws(source)
