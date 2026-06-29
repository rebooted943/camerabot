"""Buy-side providers: where ArbitrageSniper looks for cheap listings."""

from __future__ import annotations

from .base import BaseProvider
from .backmarket import BackmarketProvider
from .ebay_it import EbayItProvider
from .facebook import FacebookMarketplaceProvider
from .olx import OlxProvider
from .publi24 import Publi24Provider
from .subito import SubitoProvider
from .vinted import VintedProvider

# Registry consumed by main.py. Order = scan order (Italy, then Romania).
ALL_PROVIDERS: list[type[BaseProvider]] = [
    SubitoProvider,
    EbayItProvider,
    BackmarketProvider,
    FacebookMarketplaceProvider,
    OlxProvider,
    Publi24Provider,
    VintedProvider,
]

__all__ = [
    "BaseProvider",
    "BackmarketProvider",
    "EbayItProvider",
    "FacebookMarketplaceProvider",
    "OlxProvider",
    "Publi24Provider",
    "SubitoProvider",
    "VintedProvider",
    "ALL_PROVIDERS",
]
