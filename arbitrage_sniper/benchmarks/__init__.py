"""Valuation benchmarks: how ArbitrageSniper prices an item.

- MPB    -> Primary / floor (safety) price. Risk-zero exit.
- eBay   -> Secondary / retail target (sold-item average). Max gain.
- F64    -> Secondary / retail reference (RO used section).
"""

from __future__ import annotations

from .base import BaseBenchmark
from .ebay import EbayBenchmark
from .f64 import F64Benchmark
from .mpb import MpbBenchmark

__all__ = [
    "BaseBenchmark",
    "MpbBenchmark",
    "EbayBenchmark",
    "F64Benchmark",
]
