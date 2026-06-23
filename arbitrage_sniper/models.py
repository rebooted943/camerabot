"""Standardised data structures shared across the whole pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


class Condition(str, Enum):
    """Normalised condition buckets (maps roughly onto MPB grading)."""

    NEW = "new"
    LIKE_NEW = "like_new"
    EXCELLENT = "excellent"
    GOOD = "good"
    WELL_USED = "well_used"
    FOR_PARTS = "for_parts"
    UNKNOWN = "unknown"


# Words that should down-rank or flag a listing regardless of price.
RED_FLAG_KEYWORDS = {
    "defect",
    "defecta",
    "defect",
    "fungus",
    "ciuperca",
    "mold",
    "mucegai",
    "broken",
    "stricat",
    "nu functioneaza",
    "not working",
    "spare",
    "piese",
    "for parts",
    "shutter error",
    "err",
    "scam",
    "replica",
    "fake",
    "scratch on sensor",
    "zgarieturi senzor",
}


@dataclass
class Item:
    """Standardised listing returned by every provider.

    The first seven fields are the contract required by the spec; the rest are
    optional metadata used for red-flag detection and de-duplication.
    """

    id: str
    title: str
    price: float
    link: str
    platform: str
    condition: str = Condition.UNKNOWN.value
    image_url: Optional[str] = None

    # --- optional enrichment (never required from a provider) ---
    currency: str = "EUR"
    description: str = ""
    location: Optional[str] = None
    seller_name: Optional[str] = None
    seller_is_new: bool = False
    posted_at: Optional[str] = None

    def __post_init__(self) -> None:
        # Defensive normalisation so downstream maths never explodes.
        if self.price is None:
            self.price = 0.0
        self.price = float(self.price)
        self.title = (self.title or "").strip()
        if not self.id:
            self.id = self.fingerprint()

    def fingerprint(self) -> str:
        """Stable hash used when a platform does not expose a clean id.

        Built from the *canonical* link (query/fragment stripped) so the same
        ad always maps to the same key across runs even if tracking params or
        the price-in-title change. Falls back to the title when there is no link.
        """
        clean_link = self._canonical_link()
        basis = clean_link or self.title
        raw = f"{self.platform}|{basis}".lower()
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _canonical_link(self) -> str:
        if not self.link:
            return ""
        try:
            parts = urlsplit(self.link)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except Exception:
            return self.link

    @property
    def unique_key(self) -> str:
        """Globally-unique de-dup key stored in SQLite."""
        return f"{self.platform}:{self.id}"

    def red_flags(self) -> list[str]:
        """Detect risky signals in the title/description/seller metadata."""
        flags: list[str] = []
        haystack = f"{self.title} {self.description}".lower()
        for kw in RED_FLAG_KEYWORDS:
            if kw in haystack:
                flags.append(f"keyword:'{kw}'")
        if self.seller_is_new:
            flags.append("seller:newly-registered")
        if self.condition in {Condition.FOR_PARTS.value, Condition.WELL_USED.value}:
            flags.append(f"condition:{self.condition}")
        # De-duplicate while preserving order.
        return list(dict.fromkeys(flags))


@dataclass
class Benchmark:
    """A single price reference returned by a benchmark module."""

    source: str  # e.g. "mpb", "ebay", "f64"
    value: Optional[float]  # price in EUR (None == lookup failed)
    currency: str = "EUR"
    sample_size: int = 1  # e.g. number of eBay sold items averaged
    url: Optional[str] = None
    note: str = ""

    @property
    def available(self) -> bool:
        return self.value is not None and self.value > 0


@dataclass
class Alert:
    """The output of the arbitrage engine for a triggered listing."""

    item: Item
    target_label: str
    mpb_price: float
    ebay_price: Optional[float]
    f64_price: Optional[float]
    margin_used: float

    @property
    def safe_gain(self) -> float:
        """Risk-zero gain = MPB floor price - purchase price."""
        return round(self.mpb_price - self.item.price, 2)

    @property
    def safe_gain_pct(self) -> float:
        if self.item.price <= 0:
            return 0.0
        return round((self.safe_gain / self.item.price) * 100, 1)

    @property
    def potential_gain(self) -> Optional[float]:
        """Max gain = average eBay-sold price - purchase price."""
        if self.ebay_price is None:
            return None
        return round(self.ebay_price - self.item.price, 2)

    @property
    def red_flags(self) -> list[str]:
        return self.item.red_flags()


_PRICE_RE = re.compile(r"[-+]?\d[\d.\s,]*")


def parse_price(text: Optional[str]) -> Optional[float]:
    """Best-effort price parser for noisy marketplace strings.

    Handles European (1.234,56) and Anglo (1,234.56) groupings.
    """
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = _PRICE_RE.search(str(text).replace("\xa0", " "))
    if not match:
        return None
    raw = match.group(0).strip().replace(" ", "")
    if "," in raw and "." in raw:
        # Whichever separator comes last is the decimal separator.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # Ambiguous: treat comma as decimal if it looks like cents.
        if re.search(r",\d{1,2}$", raw):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None
