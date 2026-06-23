"""Abstract base + tiny in-memory TTL cache for benchmark lookups."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from ..browser import BrowserManager
from ..models import Benchmark

logger = logging.getLogger("arbitrage_sniper.benchmarks")


class BaseBenchmark(ABC):
    """Contract for a price-reference source.

    Benchmark values are relatively stable within a single run (and across a
    few runs), so we memoise per-key results to avoid hammering the sources.
    """

    name = "base"
    #: cache lifetime in seconds (benchmarks change slowly).
    ttl = 6 * 3600

    def __init__(self, browser: BrowserManager) -> None:
        self.browser = browser
        self._cache: dict[str, tuple[float, Benchmark]] = {}

    @abstractmethod
    async def _lookup(self, key: str, **kwargs) -> Benchmark:
        """Perform the actual (network) lookup for ``key``."""
        raise NotImplementedError

    async def get(self, key: str, **kwargs) -> Benchmark:
        """Cached, error-isolated benchmark fetch."""
        now = time.time()
        cached = self._cache.get(key)
        if cached and (now - cached[0]) < self.ttl:
            return cached[1]
        try:
            result = await self._lookup(key, **kwargs)
        except Exception as exc:
            logger.exception("[%s] lookup failed for '%s': %s", self.name, key, exc)
            result = Benchmark(source=self.name, value=None, note=f"error: {exc}")
        self._cache[key] = (now, result)
        return result

    @staticmethod
    def _avg(values: list[float], trim: float = 0.1) -> Optional[float]:
        """Trimmed mean to dampen outliers (e.g. mispriced sold listings)."""
        clean = sorted(v for v in values if v and v > 0)
        if not clean:
            return None
        if len(clean) >= 5 and trim > 0:
            k = int(len(clean) * trim)
            clean = clean[k: len(clean) - k] or clean
        return round(sum(clean) / len(clean), 2)
