"""Call an OpenAI-compatible chat model. Rules and retrieval stay outside this module."""

import json
import re
from typing import Any, Callable

import httpx
from pydantic import ValidationError

from app.schemas.review import Extraction

PROMPT = """You extract six fields from a short contract memo.

Return JSON with buyer, supplier, contract_date, total_amount, currency, payment_terms_days, obligations, and evidence.
contract_date is YYYY-MM-DD or null. total_amount is a number or null. currency is GBP, EUR, USD, or null. payment_terms_days is an integer or null.
obligations is a list of at most three short strings.
evidence maps each of the six field names to a verbatim quote copied from the memo, or null when the value is null.

Use a null value when the memo does not state that field. Do not guess a missing party, price, currency, or payment term.
The contract date is the date the parties signed or the award was made, not a later start date.
The total amount is the contract sum, not damages, a daily rate, a previous year's price, or a price the parties rejected.
The payment term is the number of days until the invoice is due, not a later interest trigger.
The currency is the currency of that contract sum.
Each quote must contain only the words that state that field. Copy them exactly.

Memo:
{memo}
"""


class SchemaError(Exception):
    pass


class ModelError(Exception):
    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


def parse_model_json(text: str) -> Extraction:
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("response was not json") from exc
    if not isinstance(payload, dict):
        raise ValueError("response was not an object")
    obligations = payload.get("obligations") or []
    if not isinstance(obligations, list):
        raise ValueError("obligations was not a list")
    payload["obligations"] = [str(item) for item in obligations[:3]]
    evidence = payload.get("evidence") or {}
    if not isinstance(evidence, dict):
        raise ValueError("evidence was not an object")
    payload["evidence"] = {str(key): value for key, value in evidence.items()}
    try:
        return Extraction.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("response did not match the schema") from exc


class GeminiExtractor:
    def __init__(
        self,
        api_key: str,
        model: str = "Qwen/Qwen2.5-7B-Instruct",
        post: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        base_url: str = "https://api.siliconflow.cn/v1/chat/completions",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._post = post or self._default_post

    def _default_post(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "content-type": "application/json",
                },
                json=body,
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise ModelError("model_unreachable") from exc
        if response.status_code == 429:
            raise ModelError("model_rate_limited")
        if response.status_code >= 400:
            raise ModelError("model_error")
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ModelError("model_empty")
        text = ((choices[0].get("message") or {}).get("content")) or ""
        usage = data.get("usage") or {}
        return {
            "text": text,
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
        }

    def _body(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }

    def extract(self, text: str) -> tuple[Extraction, dict[str, Any]]:
        prompt = PROMPT.format(memo=text)
        last_error = "invalid json"
        usage: dict[str, Any] = {}
        for attempt in range(2):
            if attempt:
                prompt = (
                    f"{PROMPT.format(memo=text)}\n\n"
                    f"The previous response failed validation: {last_error}. "
                    "Return only the JSON object."
                )
            result = self._post(self._body(prompt))
            usage = {
                "model": self.model,
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
            }
            try:
                return parse_model_json(result["text"]), usage
            except ValueError as exc:
                last_error = str(exc)
        raise SchemaError(last_error)
