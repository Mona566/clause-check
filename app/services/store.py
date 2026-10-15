from decimal import Decimal
from typing import Any


class MemoryStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def put(self, record: dict[str, Any]) -> None:
        self.records[record["review_id"]] = record

    def get(self, review_id: str) -> dict[str, Any] | None:
        return self.records.get(review_id)


def _to_dynamo(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _to_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_dynamo(item) for item in value]
    return value


def _from_dynamo(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: _from_dynamo(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_from_dynamo(item) for item in value]
    return value


class DynamoStore:
    def __init__(self, table: Any) -> None:
        self.table = table

    def put(self, record: dict[str, Any]) -> None:
        self.table.put_item(Item=_to_dynamo(record))

    def get(self, review_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key={"review_id": review_id})
        item = response.get("Item")
        if item is None:
            return None
        return _from_dynamo(item)
