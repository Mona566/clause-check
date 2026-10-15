from app.services.extract import GeminiExtractor
from app.services.pipeline import Pipeline
from app.services.retrieve import Bm25Retriever
from app.services.store import DynamoStore, MemoryStore
from app.core.config import load_settings


def build_pipeline() -> tuple[Pipeline, object]:
    settings = load_settings()
    extractor = None
    if settings.gemini_api_key:
        extractor = GeminiExtractor(
            settings.gemini_api_key,
            settings.gemini_model,
            base_url=settings.model_base_url,
        )
    if settings.store == "dynamodb":
        import boto3

        table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(
            settings.dynamodb_table
        )
        store = DynamoStore(table)
    else:
        store = MemoryStore()
    return Pipeline(extractor, Bm25Retriever.load(settings.corpus_dir), store), settings
