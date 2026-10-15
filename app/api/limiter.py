import time
from collections import defaultdict


class Limiter:
    def __init__(self, limit: int = 10, window_seconds: float = 60, now=time.monotonic) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.now = now
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, key: str) -> bool:
        moment = self.now()
        recent = [hit for hit in self._hits[key] if moment - hit < self.window_seconds]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(moment)
        self._hits[key] = recent
        return True
