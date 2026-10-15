"""Score the dev set. The holdout split stays unread unless --holdout is passed."""

import argparse
import json
import sys
from pathlib import Path

from app.core.config import ROOT, load_settings
from app.services.extract import GeminiExtractor
from app.services.pipeline import Pipeline
from app.services.retrieve import Bm25Retriever
from app.services.score import score_review
from app.services.store import MemoryStore


def assert_split_allowed(split: str, holdout: bool) -> None:
    if split == "holdout" and not holdout:
        raise SystemExit("holdout stays sealed; pass --holdout only after the prompt is frozen")


def load_pairs(folder: Path) -> list[tuple[str, dict]]:
    pairs = []
    for path in sorted(folder.glob("memo-*.txt")):
        gold = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        pairs.append((path.read_text(encoding="utf-8"), gold))
    return pairs


def summarise(results: list[dict]) -> dict:
    field_hits = sum(item["field_hits"] for item in results)
    evidence_hits = sum(item["evidence_hits"] for item in results)
    total = sum(item["total"] for item in results)
    return {
        "documents": len(results),
        "field_accuracy": _rate(field_hits, total),
        "evidence_validity": _rate(evidence_hits, total),
        "field_hits": field_hits,
        "evidence_hits": evidence_hits,
        "total": total,
    }


def _rate(hits: int, total: int) -> float | None:
    if total == 0:
        return None
    return round(100 * hits / total, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--holdout", action="store_true")
    args = parser.parse_args(argv)
    assert_split_allowed(args.split, args.holdout)
    settings = load_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set", file=sys.stderr)
        return 1
    folder = ROOT / "eval" / args.split
    pairs = load_pairs(folder)
    pipeline = Pipeline(
        GeminiExtractor(settings.gemini_api_key, settings.gemini_model),
        Bm25Retriever.load(settings.corpus_dir),
        MemoryStore(),
    )
    results = []
    for text, gold in pairs:
        audit = pipeline.run(text)
        results.append(score_review(gold, audit, text))
    print(json.dumps(summarise(results), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
