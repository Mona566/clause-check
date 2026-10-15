"""Lambda Function URL adapter. The local API uses the same pipeline.run."""

import base64
import json
from typing import Any
from urllib.parse import unquote

from app.services.documents import DocumentError, load_document
from app.services.present import ERROR_STATUS, public_view

_pipeline = None
_token = None


def _defaults():
    global _pipeline, _token
    if _pipeline is None:
        from app.wiring import build_pipeline

        pipeline, settings = build_pipeline()
        _pipeline = pipeline
        _token = settings.api_token
    return _pipeline, _token


def _authorized(event: dict[str, Any], token: str) -> bool:
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    authorization = headers.get("authorization", "")
    return authorization == f"Bearer {token}" and bool(token)


def _body_bytes(event: dict[str, Any]) -> tuple[str, bytes]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw)
        payload = json.loads(raw)
    else:
        payload = json.loads(raw) if raw else {}
    filename = payload.get("filename") or "memo.txt"
    if payload.get("text") is not None:
        return filename, str(payload["text"]).encode()
    if payload.get("content_base64"):
        return filename, base64.b64decode(payload["content_base64"])
    return filename, b""


def handler(event: dict[str, Any], context: Any = None, pipeline=None, token: str | None = None) -> dict[str, Any]:
    if pipeline is None or token is None:
        pipeline, token = _defaults()
    path = unquote(event.get("rawPath") or event.get("path") or "/")
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET").upper()
    if path == "/health" and method == "GET":
        return _response(200, {"status": "ok"})
    if not _authorized(event, token):
        return _response(401, {"detail": "unauthorized"})
    if method == "GET" and path.startswith("/reviews/"):
        review_id = path.split("/reviews/", 1)[1].strip("/")
        record = pipeline.store.get(review_id)
        if record is None:
            return _response(404, {"detail": "not_found"})
        return _response(200, public_view(record))
    if method == "POST" and path.rstrip("/") == "/reviews":
        try:
            filename, data = _body_bytes(event)
            text = load_document(filename, data)
        except (DocumentError, json.JSONDecodeError, ValueError) as exc:
            error_type = getattr(exc, "error_type", "invalid_text")
            status = getattr(exc, "status_code", 422)
            return _response(status, {"detail": error_type})
        audit = pipeline.run(text)
        status = ERROR_STATUS.get(audit.get("error_type") or "", 200)
        body = public_view(audit) if status == 200 else {"detail": public_view(audit)}
        return _response(status, body)
    return _response(404, {"detail": "not_found"})


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
