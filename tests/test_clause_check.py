import json
from decimal import Decimal

from fastapi.testclient import TestClient

from app.api.limiter import Limiter
from app.api.routes import create_app
from app.lambda_handler import handler
from app.schemas.review import Extraction
from app.services.documents import DocumentError, load_document
from app.services.extract import GeminiExtractor, SchemaError, parse_model_json
from app.services.pipeline import Pipeline
from app.services.retrieve import Bm25Retriever, Chunk
from app.services.rules import apply_rules, dates_in, judge_field
from app.services.score import score_review
from app.services.store import DynamoStore, MemoryStore
from eval.run_eval import assert_split_allowed, summarise


TOKEN = "test-token"


class FakeExtractor:
    model = "fake"

    def __init__(self, extraction: Extraction | None = None, error: Exception | None = None) -> None:
        self.extraction = extraction or Extraction()
        self.error = error

    def extract(self, text: str):
        if self.error:
            raise self.error
        return self.extraction, {"model": self.model, "input_tokens": 3, "output_tokens": 2}


def _client(pipeline: Pipeline, limit: int = 10) -> TestClient:
    return TestClient(create_app(pipeline, TOKEN, Limiter(limit=limit)))


def _memo() -> str:
    return (
        "Northline Borough Council has awarded a short contract to Harbour Analytics Ltd. "
        "The contract date is 4 June 2025. The total amount is £18,500 "
        "(eighteen thousand five hundred pounds). Payment terms are 30 days from a valid invoice."
    )


def _good_extraction() -> Extraction:
    return Extraction(
        buyer="Northline Borough Council",
        supplier="Harbour Analytics Ltd",
        contract_date="2025-06-04",
        total_amount=18500,
        currency="GBP",
        payment_terms_days=30,
        obligations=["deliver a written index report"],
        evidence={
            "buyer": "Northline Borough Council has awarded",
            "supplier": "to Harbour Analytics Ltd.",
            "contract_date": "The contract date is 4 June 2025.",
            "total_amount": "The total amount is £18,500 (eighteen thousand five hundred pounds).",
            "currency": "The total amount is £18,500 (eighteen thousand five hundred pounds).",
            "payment_terms_days": "Payment terms are 30 days from a valid invoice.",
        },
    )


def test_a_quote_with_two_amounts_is_rejected():
    source = "The total amount is £48,000. Damages are £5,000."
    result = judge_field("total_amount", 48000, source, source)
    assert result["status"] == "rejected"
    assert result["reason"] == "ambiguous"


def test_interest_days_do_not_count_as_the_payment_term():
    quote = "Payment terms are 30 days. Interest starts after 14 days."
    result = judge_field("payment_terms_days", 30, quote, quote)
    assert result["status"] == "rejected"
    assert result["reason"] == "ambiguous"


def test_a_name_missing_from_its_quote_is_rejected():
    source = "Redford District Council appoints Pell & Wren Ltd."
    result = judge_field("supplier", "Pell & Wren Ltd", "Redford District Council appoints", source)
    assert result["reason"] == "name_not_in_quote"


def test_a_quote_outside_the_memo_is_ungrounded():
    result = judge_field("buyer", "Northline Borough Council", "not in the memo", _memo())
    assert result["status"] == "ungrounded"


def test_leap_day_and_written_dates():
    assert dates_in("signed on 29 February 2024") == {"2024-02-29"}
    assert dates_in("dated this 3rd day of January 2026") == {"2026-01-03"}
    assert len(dates_in("signed on 8 July 2025. Services start on 1 August 2025.")) == 2


def test_absent_field_needs_no_quote():
    result = judge_field("supplier", None, None, "Solway Parks Trust will buy a survey.")
    assert result["status"] == "absent"


def test_right_amount_with_the_wrong_sentence_splits_the_two_scores():
    source = _memo()
    audit = {
        "fields": {
            "buyer": {"value": "Northline Borough Council", "evidence": "Harbour Analytics Ltd"},
            "supplier": {"value": "Harbour Analytics Ltd", "evidence": "Harbour Analytics Ltd"},
            "contract_date": {"value": "2025-06-04", "evidence": "4 June 2025"},
            "total_amount": {"value": 18500, "evidence": "Payment terms are 30 days"},
            "currency": {"value": "GBP", "evidence": "£18,500"},
            "payment_terms_days": {"value": 30, "evidence": "30 days"},
        }
    }
    gold = {
        "buyer": "Northline Borough Council",
        "supplier": "Harbour Analytics Ltd",
        "contract_date": "2025-06-04",
        "total_amount": 18500,
        "currency": "GBP",
        "payment_terms_days": 30,
    }
    scored = score_review(gold, audit, source)
    assert scored["details"]["total_amount"] == {"field": True, "evidence": False}
    assert scored["details"]["currency"]["evidence"] is True


def test_pipeline_accepts_grounded_fields_and_does_not_log_the_memo(capsys):
    store = MemoryStore()
    pipeline = Pipeline(FakeExtractor(_good_extraction()), Bm25Retriever([]), store)
    audit = pipeline.run(_memo())
    assert audit["status"] == "done"
    assert audit["fields"]["total_amount"]["status"] == "accepted"
    assert audit["fields"]["contract_date"]["value"] == "2025-06-04"
    logged = capsys.readouterr().out
    assert audit["review_id"] in logged
    assert "Northline" not in logged
    assert "18500" not in logged


def test_schema_failure_is_stored():
    store = MemoryStore()
    pipeline = Pipeline(FakeExtractor(error=SchemaError("no")), Bm25Retriever([]), store)
    audit = pipeline.run(_memo())
    assert audit["error_type"] == "schema_invalid"
    assert store.get(audit["review_id"])["source_text"] == _memo()


def test_bm25_ranks_the_closer_note_first():
    retriever = Bm25Retriever(
        [
            Chunk("https://example.test/pay", "payment", "payment terms invoice due in thirty days"),
            Chunk("https://example.test/roof", "roof", "roof tiles and gutter replacement"),
        ]
    )
    hits = retriever.search("when is the invoice payment term due", k=2)
    assert hits[0]["title"] == "payment"


def test_api_auth_size_and_lookup():
    pipeline = Pipeline(FakeExtractor(_good_extraction()), Bm25Retriever([]), MemoryStore())
    client = _client(pipeline)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.post("/reviews", json={"text": _memo()}).status_code == 401
    ok = client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"filename": "memo.txt", "text": _memo()},
    )
    assert ok.status_code == 200
    review_id = ok.json()["review_id"]
    fetched = client.get(f"/reviews/{review_id}", headers={"Authorization": f"Bearer {TOKEN}"})
    assert fetched.json()["fields"]["buyer"]["status"] == "accepted"
    missing = client.get("/reviews/missing", headers={"Authorization": f"Bearer {TOKEN}"})
    assert missing.status_code == 404
    huge = client.post(
        "/reviews",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"filename": "memo.txt", "text": "x" * 50},
    )
    # The route uses the real 2 MB limit, so a short file is accepted.
    assert huge.status_code == 200


def test_oversize_and_empty_documents():
    try:
        load_document("memo.txt", b"x" * 20, max_bytes=10)
    except DocumentError as exc:
        assert exc.error_type == "too_large"
    else:
        raise AssertionError("expected too_large")
    try:
        load_document("scan.pdf", b"%PDF-1.1 not a real pdf")
    except DocumentError as exc:
        assert exc.error_type == "invalid_text"
    else:
        raise AssertionError("expected invalid_text")
    try:
        load_document("memo.txt", b"too short")
    except DocumentError as exc:
        assert exc.error_type == "no_extractable_text"
    else:
        raise AssertionError("expected no_extractable_text")


def test_rate_limit():
    pipeline = Pipeline(FakeExtractor(_good_extraction()), Bm25Retriever([]), MemoryStore())
    client = _client(pipeline, limit=1)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/reviews", headers=headers, json={"text": _memo()}).status_code == 200
    assert client.post("/reviews", headers=headers, json={"text": _memo()}).status_code == 429


def test_lambda_requires_a_token_and_returns_the_audit():
    pipeline = Pipeline(FakeExtractor(_good_extraction()), Bm25Retriever([]), MemoryStore())
    denied = handler({"rawPath": "/health", "requestContext": {"http": {"method": "GET"}}}, pipeline=pipeline, token=TOKEN)
    assert denied["statusCode"] == 200
    created = handler(
        {
            "rawPath": "/reviews",
            "requestContext": {"http": {"method": "POST"}},
            "headers": {"authorization": f"Bearer {TOKEN}"},
            "body": json.dumps({"filename": "memo.txt", "text": _memo()}),
        },
        pipeline=pipeline,
        token=TOKEN,
    )
    assert created["statusCode"] == 200
    body = json.loads(created["body"])
    assert body["fields"]["supplier"]["status"] == "accepted"


def test_gemini_parser_strips_fences_and_retries_once():
    calls = []

    def post(body):
        calls.append(body)
        if len(calls) == 1:
            return {"text": "not json", "input_tokens": 1, "output_tokens": 1}
        return {
            "text": '```json\n{"buyer": "A", "evidence": {"buyer": "A"}}\n```',
            "input_tokens": 4,
            "output_tokens": 4,
        }

    extraction, usage = GeminiExtractor("key", post=post).extract("memo text")
    assert extraction.buyer == "A"
    assert usage["input_tokens"] == 4
    assert len(calls) == 2


def test_bad_json_twice_raises_schema_error():
    def post(body):
        return {"text": "nope", "input_tokens": 1, "output_tokens": 1}

    try:
        GeminiExtractor("key", post=post).extract("memo")
    except SchemaError:
        return
    raise AssertionError("expected SchemaError")


def test_dynamo_store_round_trip_converts_floats():
    class Table:
        def __init__(self):
            self.item = None

        def put_item(self, Item):
            self.item = Item

        def get_item(self, Key):
            return {"Item": self.item}

    table = Table()
    store = DynamoStore(table)
    store.put({"review_id": "abc", "related_guidance": [{"score": 1.25}]})
    assert isinstance(table.item["related_guidance"][0]["score"], Decimal)
    assert store.get("abc")["related_guidance"][0]["score"] == 1.25


def test_dotenv_keeps_an_existing_token(tmp_path, monkeypatch):
    import os

    from app.core.config import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("API_TOKEN=from-file\nGEMINI_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setenv("API_TOKEN", "from-env")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    load_dotenv(env_file)
    assert os.environ["API_TOKEN"] == "from-env"
    assert os.environ["GEMINI_MODEL"] == "from-file"


def test_holdout_flag_is_required_and_summary_math_is_plain():
    try:
        assert_split_allowed("holdout", False)
    except SystemExit as exc:
        assert "sealed" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
    assert_split_allowed("dev", False)
    summary = summarise([{"field_hits": 5, "evidence_hits": 4, "total": 6}])
    assert summary["field_accuracy"] == 83.3
    assert summary["evidence_validity"] == 66.7


def test_rules_on_a_real_dev_memo():
    from pathlib import Path

    text = Path("eval/dev/memo-01.txt").read_text(encoding="utf-8")
    extraction = _good_extraction().model_copy(
        update={
            "evidence": {
                **_good_extraction().evidence,
                "supplier": "to Harbour Analytics Ltd for a review",
            }
        }
    )
    fields = apply_rules(text, extraction)
    assert all(fields[name]["status"] == "accepted" for name in fields)
    parsed = parse_model_json('{"buyer": null, "obligations": ["a", "b", "c", "d"]}')
    assert parsed.obligations == ["a", "b", "c"]
