import json
import sys
from typing import Any


LOG_FIELDS = (
    "review_id",
    "stage",
    "ms",
    "model",
    "input_tokens",
    "output_tokens",
    "error_type",
)


def log_event(payload: dict[str, Any]) -> None:
    line = {key: payload.get(key) for key in LOG_FIELDS}
    sys.stdout.write(json.dumps(line, default=str) + "\n")
    sys.stdout.flush()
