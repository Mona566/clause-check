"""Deterministic checks. A field is accepted only when its quote supports it."""

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from app.schemas.review import SCORED_FIELDS, Extraction
from app.services.textutil import normalize_ws, quote_in_source

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_ONES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_AMOUNT_WORDS = set(_ONES) | set(_TENS) | {"hundred", "thousand", "and"}


@dataclass(frozen=True)
class Parsed:
    value: Any
    reason: str | None = None


def _iso_date(year: int, month: int, day: int) -> str | None:
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def dates_in(text: str) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        iso = _iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso:
            found.add(iso)
    written = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+day)?\s+of\s+([A-Za-z]+)\s+(\d{4})\b",
        re.IGNORECASE,
    )
    plain = re.compile(
        r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\b",
        re.IGNORECASE,
    )
    for pattern in (written, plain):
        for match in pattern.finditer(text):
            month = _MONTHS.get(match.group(2).lower())
            if month is None:
                continue
            iso = _iso_date(int(match.group(3)), month, int(match.group(1)))
            if iso:
                found.add(iso)
    return found


def _parse_amount_phrase(words: list[str]) -> int | None:
    if "thousand" not in words and "hundred" not in words:
        return None
    total = 0
    current = 0
    for word in words:
        if word == "and":
            continue
        if word in _ONES:
            current += _ONES[word]
        elif word in _TENS:
            current += _TENS[word]
        elif word == "hundred":
            current = (current or 1) * 100
        elif word == "thousand":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
    total += current
    return total or None


def word_amounts(text: str) -> set[int]:
    tokens = re.findall(r"[a-z]+", text.lower())
    found: set[int] = set()
    index = 0
    while index < len(tokens):
        if tokens[index] not in _ONES and tokens[index] not in _TENS:
            index += 1
            continue
        end = index
        while end < len(tokens) and tokens[end] in _AMOUNT_WORDS:
            end += 1
        value = _parse_amount_phrase(tokens[index:end])
        if value is not None:
            found.add(value)
        index = max(end, index + 1)
    return found


def amounts_in(text: str) -> set[int]:
    found: set[int] = set()
    number = r"(\d{1,3}(?:,\d{3})+|\d+)"
    patterns = (
        rf"(?:£|\$)\s*{number}",
        rf"\b(?:GBP|EUR|USD)\s*{number}\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            found.add(int(match.group(1).replace(",", "")))
    found |= word_amounts(text)
    return found


def currencies_in(text: str) -> set[str]:
    found: set[str] = set()
    if "£" in text or re.search(r"\bpounds?\b|\bGBP\b|\bsterling\b", text, re.IGNORECASE):
        found.add("GBP")
    if re.search(r"\beuros?\b|\bEUR\b", text, re.IGNORECASE):
        found.add("EUR")
    if "$" in text or re.search(r"\bUSD\b|\bdollars?\b", text, re.IGNORECASE):
        found.add("USD")
    return found


def days_in(text: str) -> set[int]:
    return {
        int(match.group(1))
        for match in re.finditer(r"\b(?:net\s+)?(\d+)\s+days\b", text, re.IGNORECASE)
    }


def canonical_currency(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().upper()
    if token in {"GBP", "POUND", "POUNDS", "STERLING"}:
        return "GBP"
    if token in {"EUR", "EURO", "EUROS"}:
        return "EUR"
    if token in {"USD", "DOLLAR", "DOLLARS", "US DOLLAR", "US DOLLARS"}:
        return "USD"
    return None


def predicted_value(field: str, raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if field in {"buyer", "supplier"}:
        return str(raw).strip()
    if field == "currency":
        return canonical_currency(raw)
    if field == "total_amount":
        if isinstance(raw, float) and not raw.is_integer():
            return raw
        return int(raw)
    if field == "payment_terms_days":
        return int(raw)
    if field == "contract_date":
        found = dates_in(str(raw))
        if len(found) == 1:
            return next(iter(found))
        return str(raw).strip()
    return raw


def _one(values: set[Any], empty_reason: str = "unparsed") -> Parsed:
    if not values:
        return Parsed(None, empty_reason)
    if len(values) > 1:
        return Parsed(None, "ambiguous")
    return Parsed(next(iter(values)))


def parse_quote(field: str, quote: str) -> Parsed:
    if field == "contract_date":
        return _one(dates_in(quote))
    if field == "total_amount":
        return _one(amounts_in(quote))
    if field == "currency":
        return _one(currencies_in(quote))
    if field == "payment_terms_days":
        return _one(days_in(quote))
    return Parsed(None, "unparsed")


def judge_field(field: str, raw: Any, quote: str | None, source: str) -> dict[str, Any]:
    if raw is None or raw == "":
        return {"value": None, "evidence": None, "status": "absent", "reason": None}
    if not quote_in_source(quote, source):
        return {
            "value": predicted_value(field, raw),
            "evidence": quote,
            "status": "ungrounded",
            "reason": "quote_not_in_source",
        }
    assert quote is not None
    if field in {"buyer", "supplier"}:
        name = str(raw).strip()
        if normalize_ws(name) in normalize_ws(quote):
            return {"value": name, "evidence": quote, "status": "accepted", "reason": None}
        return {
            "value": name,
            "evidence": quote,
            "status": "rejected",
            "reason": "name_not_in_quote",
        }
    parsed = parse_quote(field, quote)
    claimed = predicted_value(field, raw)
    if parsed.reason:
        return {
            "value": claimed,
            "evidence": quote,
            "status": "rejected",
            "reason": parsed.reason,
        }
    if claimed != parsed.value:
        return {
            "value": claimed,
            "evidence": quote,
            "status": "rejected",
            "reason": "parser_mismatch",
        }
    return {"value": parsed.value, "evidence": quote, "status": "accepted", "reason": None}


def apply_rules(source: str, extraction: Extraction) -> dict[str, dict[str, Any]]:
    return {
        field: judge_field(field, *extraction.claim(field), source)
        for field in SCORED_FIELDS
    }


def evidence_supports(field: str, gold: Any, quote: str | None, source: str) -> bool:
    """True when the quote alone recovers the gold value from the source text."""
    if gold is None:
        return True
    if not quote_in_source(quote, source):
        return False
    assert quote is not None
    if field in {"buyer", "supplier"}:
        return normalize_ws(str(gold)) in normalize_ws(quote)
    parsed = parse_quote(field, quote)
    return parsed.reason is None and parsed.value == gold
