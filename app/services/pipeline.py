import time
import uuid
from typing import Any, Callable, Protocol

from app.schemas.review import Extraction
from app.services.extract import ModelError, SchemaError
from app.services.logging import log_event
from app.services.rules import apply_rules


class Extractor(Protocol):
    model: str

    def extract(self, text: str) -> tuple[Extraction, dict[str, Any]]: ...


class Retriever(Protocol):
    def search(self, query: str, k: int = 3) -> list[dict[str, object]]: ...


class Store(Protocol):
    def put(self, record: dict[str, Any]) -> None: ...

    def get(self, review_id: str) -> dict[str, Any] | None: ...


class Pipeline:
    def __init__(
        self,
        extractor: Extractor | None,
        retriever: Retriever,
        store: Store,
        logger: Callable[[dict[str, Any]], None] = log_event,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.extractor = extractor
        self.retriever = retriever
        self.store = store
        self.logger = logger
        self.clock = clock

    def run(self, text: str) -> dict[str, Any]:
        review_id = str(uuid.uuid4())
        started = self.clock()
        usage: dict[str, Any] = {"model": None, "input_tokens": None, "output_tokens": None}
        try:
            if self.extractor is None:
                raise ModelError("model_not_configured")
            extraction, usage = self.extractor.extract(text)
            audit = self._audit(review_id, text, extraction, usage, error_type=None)
        except SchemaError:
            audit = self._failed(review_id, usage, "schema_invalid")
        except ModelError as exc:
            audit = self._failed(review_id, usage, exc.error_type)
        audit["ms"] = int((self.clock() - started) * 1000)
        self.store.put(_stored(audit, text))
        self.logger(
            {
                "review_id": review_id,
                "stage": audit["status"],
                "ms": audit["ms"],
                "model": usage.get("model"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "error_type": audit.get("error_type"),
            }
        )
        return audit

    def _audit(
        self,
        review_id: str,
        text: str,
        extraction: Extraction,
        usage: dict[str, Any],
        error_type: str | None,
    ) -> dict[str, Any]:
        return {
            "review_id": review_id,
            "status": "done",
            "model": usage.get("model"),
            "fields": apply_rules(text, extraction),
            "obligations": extraction.obligations[:3],
            "related_guidance": self.retriever.search(text, k=3),
            "error_type": error_type,
        }

    def _failed(self, review_id: str, usage: dict[str, Any], error_type: str) -> dict[str, Any]:
        return {
            "review_id": review_id,
            "status": "failed",
            "model": usage.get("model"),
            "fields": {},
            "obligations": [],
            "related_guidance": [],
            "error_type": error_type,
        }


def _stored(audit: dict[str, Any], text: str) -> dict[str, Any]:
    return {**audit, "source_text": text}
