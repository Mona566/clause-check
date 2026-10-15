import base64
import hmac
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from app.api.limiter import Limiter
from app.schemas.review import ReviewRequest
from app.services.documents import DocumentError, load_document
from app.services.pipeline import Pipeline
from app.services.present import ERROR_STATUS, public_view


def _check_token(authorization: str | None, token: str) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    presented = authorization.removeprefix("Bearer ").encode()
    expected = token.encode()
    if len(presented) != len(expected) or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def bytes_from_request(body: ReviewRequest) -> tuple[str, bytes]:
    if body.text is not None:
        data = body.text.encode()
    elif body.content_base64 is not None:
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="invalid_text") from exc
    else:
        raise HTTPException(status_code=422, detail="empty_body")
    return body.filename, data


def create_app(pipeline: Pipeline, token: str, limiter: Limiter | None = None) -> FastAPI:
    limiter = limiter or Limiter()
    app = FastAPI(title="Clause Check")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/reviews")
    def create_review(
        body: ReviewRequest,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_token(authorization, token)
        if not limiter.allow(token):
            raise HTTPException(status_code=429, detail="rate_limited")
        filename, data = bytes_from_request(body)
        try:
            text = load_document(filename, data)
        except DocumentError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.error_type) from exc
        audit = pipeline.run(text)
        status = ERROR_STATUS.get(audit.get("error_type") or "", 200)
        if status != 200:
            raise HTTPException(status_code=status, detail=public_view(audit))
        return public_view(audit)

    @app.get("/reviews/{review_id}")
    def get_review(
        review_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _check_token(authorization, token)
        record = pipeline.store.get(review_id)
        if record is None:
            raise HTTPException(status_code=404, detail="not_found")
        return public_view(record)

    return app
