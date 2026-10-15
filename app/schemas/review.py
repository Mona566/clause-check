from typing import Any

from pydantic import BaseModel, Field


SCORED_FIELDS = (
    "buyer",
    "supplier",
    "contract_date",
    "total_amount",
    "currency",
    "payment_terms_days",
)


class Extraction(BaseModel):
    buyer: str | None = None
    supplier: str | None = None
    contract_date: str | None = None
    total_amount: float | int | None = None
    currency: str | None = None
    payment_terms_days: int | None = None
    obligations: list[str] = Field(default_factory=list)
    evidence: dict[str, str | None] = Field(default_factory=dict)

    def claim(self, field: str) -> tuple[Any, str | None]:
        value = getattr(self, field)
        quote = self.evidence.get(field)
        if isinstance(quote, str):
            quote = quote.strip() or None
        return value, quote


class ReviewRequest(BaseModel):
    filename: str = "memo.txt"
    text: str | None = None
    content_base64: str | None = None
