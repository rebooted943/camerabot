"""Buy-side providers: where ArbitrageSniper looks for cheap listings."""

from __future__ import annotations

from .base import BaseProvider
from .olx import OlxProvider
from .publi24 import Publi24Provider
from .vinted import VintedProvider
from .wallapop import WallapopProvider

# Registry consumed by main.py. Order = scan order.
ALL_PROVIDERS: list[type[BaseProvider]] = [
    OlxProvider,
    VintedProvider,
    Publi24Provider,
    WallapopProvider,
]

__all__ = [
    "BaseProvider",
    "OlxProvider",
    "Publi24Provider",
    "VintedProvider",
    "WallapopProvider",
    "ALL_PROVIDERS",
]
