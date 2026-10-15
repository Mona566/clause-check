from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class DocumentError(Exception):
    def __init__(self, error_type: str, status_code: int) -> None:
        super().__init__(error_type)
        self.error_type = error_type
        self.status_code = status_code


def load_document(filename: str, data: bytes, max_bytes: int = 2_000_000, min_chars: int = 40) -> str:
    if len(data) > max_bytes:
        raise DocumentError("too_large", 413)
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ""}:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentError("invalid_text", 422) from exc
    elif suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as exc:
            raise DocumentError("invalid_text", 422) from exc
    else:
        raise DocumentError("unsupported_type", 415)
    if len(" ".join(text.split())) < min_chars:
        raise DocumentError("no_extractable_text", 422)
    return text
