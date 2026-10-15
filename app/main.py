from app.api.limiter import Limiter
from app.api.routes import create_app
from app.wiring import build_pipeline


def build_app():
    pipeline, settings = build_pipeline()
    if not settings.api_token:
        raise RuntimeError("API_TOKEN is required")
    return create_app(pipeline, settings.api_token, Limiter())


app = build_app()
