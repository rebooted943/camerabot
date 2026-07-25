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

# name -> class, for lookups by the web UI / scan selector.
PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {p.name: p for p in ALL_PROVIDERS}


def provider_names() -> list[str]:
    """All known provider names, in scan order."""
    return [p.name for p in ALL_PROVIDERS]


def resolve_providers(names) -> list[type[BaseProvider]]:
    """Map a list of provider names to classes (unknown names ignored).

    ``None`` or empty -> all providers.
    """
    if not names:
        return list(ALL_PROVIDERS)
    wanted = {str(n).strip().lower() for n in names}
    return [p for p in ALL_PROVIDERS if p.name in wanted]

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
    "PROVIDER_REGISTRY",
    "provider_names",
    "resolve_providers",
]
