import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Fill unset variables from .env. Existing environment values win."""
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    api_token: str
    gemini_api_key: str | None
    gemini_model: str
    model_base_url: str
    store: str
    dynamodb_table: str | None
    aws_region: str
    corpus_dir: Path


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        api_token=os.environ.get("API_TOKEN", ""),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
        model_base_url=os.environ.get(
            "MODEL_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions"
        ),
        store=os.environ.get("STORE", "memory"),
        dynamodb_table=os.environ.get("DYNAMODB_TABLE") or None,
        aws_region=os.environ.get("AWS_REGION", "eu-west-2"),
        corpus_dir=Path(os.environ.get("CORPUS_DIR", ROOT / "corpus")),
    )
