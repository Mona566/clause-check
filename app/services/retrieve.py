import math
import re
from dataclasses import dataclass
from pathlib import Path


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class _BM25:
    """Small Okapi BM25 so the Lambda package does not need NumPy."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_len = [len(doc) for doc in corpus]
        self.avgdl = (sum(self.doc_len) / len(corpus)) if corpus else 0.0
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for doc in corpus:
            freqs: dict[str, int] = {}
            for word in doc:
                freqs[word] = freqs.get(word, 0) + 1
            self.tf.append(freqs)
            for word in freqs:
                df[word] = df.get(word, 0) + 1
        total = len(corpus)
        self.idf = {
            word: math.log(1 + (total - freq + 0.5) / (freq + 0.5)) for word, freq in df.items()
        }

    def get_scores(self, query: list[str]) -> list[float]:
        scores = []
        for index, freqs in enumerate(self.tf):
            score = 0.0
            length = self.doc_len[index] or 1
            for word in query:
                freq = freqs.get(word)
                if not freq:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * length / (self.avgdl or 1))
                score += self.idf.get(word, 0.0) * (freq * (self.k1 + 1)) / denom
            scores.append(score)
        return scores


@dataclass(frozen=True)
class Chunk:
    source: str
    title: str
    text: str


class Bm25Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        tokens = [tokenize(chunk.text) or ["empty"] for chunk in chunks]
        self._index = _BM25(tokens) if chunks else None

    @classmethod
    def load(cls, corpus_dir: Path) -> "Bm25Retriever":
        chunks: list[Chunk] = []
        for path in sorted(corpus_dir.glob("*.txt")):
            lines = path.read_text(encoding="utf-8").splitlines()
            source = ""
            body_start = 0
            if lines and lines[0].startswith("Source:"):
                source = lines[0].split("Source:", 1)[1].strip()
                body_start = 1
            body = "\n".join(lines[body_start:]).strip()
            paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
            for paragraph in paragraphs or [body]:
                chunks.append(Chunk(source=source, title=path.stem, text=paragraph))
        return cls(chunks)

    def search(self, query: str, k: int = 3) -> list[dict[str, object]]:
        if not self.chunks or self._index is None:
            return []
        scores = self._index.get_scores(tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        passages = []
        for index, score in ranked[:k]:
            chunk = self.chunks[index]
            passages.append(
                {
                    "source": chunk.source,
                    "title": chunk.title,
                    "passage": chunk.text[:500],
                    "score": round(float(score), 4),
                }
            )
        return passages
