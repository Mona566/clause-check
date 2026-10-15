from typing import Any


PUBLIC_FIELDS = (
    "review_id",
    "status",
    "model",
    "fields",
    "obligations",
    "related_guidance",
    "error_type",
    "ms",
)

ERROR_STATUS = {
    "schema_invalid": 422,
    "model_not_configured": 503,
    "model_unreachable": 502,
    "model_rate_limited": 429,
    "model_error": 502,
    "model_empty": 502,
}


def public_view(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in PUBLIC_FIELDS}
