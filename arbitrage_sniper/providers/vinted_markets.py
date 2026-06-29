"""Vinted EU storefront registry (West + East Europe).

Vinted runs separate country domains that share the same catalog API shape
(``/api/v2/catalog/items``) but use local currencies and Datadome sessions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VintedStorefront:
    code: str
    domain: str
    currency: str
    region: str  # "west" | "east"
    label: str

    @property
    def base_url(self) -> str:
        return f"https://www.{self.domain}"


# All European Vinted storefronts (excludes US/CA/AU global sites).
EU_STOREFRONTS: tuple[VintedStorefront, ...] = (
    # --- Western Europe ---
    VintedStorefront("fr", "vinted.fr", "EUR", "west", "France"),
    VintedStorefront("de", "vinted.de", "EUR", "west", "Germany"),
    VintedStorefront("it", "vinted.it", "EUR", "west", "Italy"),
    VintedStorefront("es", "vinted.es", "EUR", "west", "Spain"),
    VintedStorefront("nl", "vinted.nl", "EUR", "west", "Netherlands"),
    VintedStorefront("be", "vinted.be", "EUR", "west", "Belgium"),
    VintedStorefront("at", "vinted.at", "EUR", "west", "Austria"),
    VintedStorefront("pt", "vinted.pt", "EUR", "west", "Portugal"),
    VintedStorefront("lu", "vinted.lu", "EUR", "west", "Luxembourg"),
    VintedStorefront("ie", "vinted.ie", "EUR", "west", "Ireland"),
    VintedStorefront("uk", "vinted.co.uk", "GBP", "west", "United Kingdom"),
    VintedStorefront("dk", "vinted.dk", "DKK", "west", "Denmark"),
    VintedStorefront("fi", "vinted.fi", "EUR", "west", "Finland"),
    VintedStorefront("se", "vinted.se", "SEK", "west", "Sweden"),
    # --- Eastern Europe ---
    VintedStorefront("pl", "vinted.pl", "PLN", "east", "Poland"),
    VintedStorefront("cz", "vinted.cz", "CZK", "east", "Czechia"),
    VintedStorefront("sk", "vinted.sk", "EUR", "east", "Slovakia"),
    VintedStorefront("hu", "vinted.hu", "HUF", "east", "Hungary"),
    VintedStorefront("ro", "vinted.ro", "RON", "east", "Romania"),
    VintedStorefront("hr", "vinted.hr", "EUR", "east", "Croatia"),
    VintedStorefront("lt", "vinted.lt", "EUR", "east", "Lithuania"),
    VintedStorefront("lv", "vinted.lv", "EUR", "east", "Latvia"),
    VintedStorefront("ee", "vinted.ee", "EUR", "east", "Estonia"),
    VintedStorefront("gr", "vinted.gr", "EUR", "east", "Greece"),
)


def active_storefronts(*, regions: str = "west,east", markets: str = "") -> list[VintedStorefront]:
    """Return storefronts to scan based on env filters.

    ``markets`` — comma-separated country codes (e.g. ``it,ro,fr``). When set,
    overrides ``regions``.
    ``regions`` — ``west``, ``east``, or ``west,east`` (default: both).
    """
    if markets.strip():
        codes = {c.strip().lower() for c in markets.split(",") if c.strip()}
        return [s for s in EU_STOREFRONTS if s.code in codes]

    region_set = {r.strip().lower() for r in regions.split(",") if r.strip()}
    if not region_set or "all" in region_set:
        return list(EU_STOREFRONTS)
    return [s for s in EU_STOREFRONTS if s.region in region_set]
