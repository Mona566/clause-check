from typing import Any

from app.schemas.review import SCORED_FIELDS
from app.services.rules import evidence_supports, predicted_value


def score_review(gold: dict[str, Any], audit: dict[str, Any], source: str) -> dict[str, Any]:
    fields = audit.get("fields") or {}
    field_hits = 0
    evidence_hits = 0
    details = {}
    for name in SCORED_FIELDS:
        gold_value = gold.get(name)
        reported = fields.get(name) or {}
        predicted = predicted_value(name, reported.get("value"))
        # Prefer the model's raw claim when the rule replaced it. The audit
        # stores the claimed value, which is what field accuracy measures.
        correct = predicted == gold_value
        quote = reported.get("evidence")
        supported = evidence_supports(name, gold_value, quote, source)
        if gold_value is None:
            supported = predicted is None
        if correct:
            field_hits += 1
        if supported:
            evidence_hits += 1
        details[name] = {"field": correct, "evidence": supported}
    total = len(SCORED_FIELDS)
    return {
        "field_hits": field_hits,
        "evidence_hits": evidence_hits,
        "total": total,
        "details": details,
    }
