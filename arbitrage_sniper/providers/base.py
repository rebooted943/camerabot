"""Abstract base class shared by every buy-side provider."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..browser import BrowserManager, jitter
from ..config import settings
from ..models import Condition, Item

logger = logging.getLogger("arbitrage_sniper.providers")


class BaseProvider(ABC):
    """Contract for a marketplace scraper.

    Subclasses implement :meth:`search` and return standardised
    :class:`~arbitrage_sniper.models.Item` objects. The base class owns the
    shared browser, politeness delays and error isolation so a single broken
    provider can never crash the whole run.
    """

    #: short, lowercase identifier used as ``Item.platform`` and in the DB.
    name: str = "base"
    #: human-friendly label for logs.
    label: str = "Base"
    #: whether this provider needs a real (stealth) browser vs plain HTTP.
    requires_browser: bool = True

    def __init__(self, browser: BrowserManager) -> None:
        self.browser = browser
        self.max_items = settings.max_items_per_provider

    @abstractmethod
    async def search(self, query: str) -> list[Item]:
        """Return listings matching ``query`` for this marketplace."""
        raise NotImplementedError

    async def safe_search(self, query: str) -> list[Item]:
        """Run :meth:`search` with error isolation and a politeness delay."""
        try:
            await jitter()
            items = await self.search(query)
            items = [it for it in items if it.price > 0][: self.max_items]
            logger.info("[%s] '%s' -> %d items", self.name, query, len(items))
            return items
        except Exception as exc:
            logger.exception("[%s] search failed for '%s': %s", self.name, query, exc)
            return []

    # --- helpers shared by subclasses ------------------------------------ #
    @staticmethod
    def normalise_condition(raw: str | None) -> str:
        """Map a free-text condition string onto our Condition enum."""
        if not raw:
            return Condition.UNKNOWN.value
        text = raw.strip().lower()
        mapping = {
            "new": Condition.NEW,
            "nou": Condition.NEW,
            "nuevo": Condition.NEW,
            "neu": Condition.NEW,
            "like new": Condition.LIKE_NEW,
            "ca nou": Condition.LIKE_NEW,
            "como nuevo": Condition.LIKE_NEW,
            "very good": Condition.EXCELLENT,
            "excellent": Condition.EXCELLENT,
            "excelent": Condition.EXCELLENT,
            "good": Condition.GOOD,
            "bun": Condition.GOOD,
            "buen estado": Condition.GOOD,
            "used": Condition.GOOD,
            "folosit": Condition.GOOD,
            "satisfactory": Condition.WELL_USED,
            "acceptable": Condition.WELL_USED,
            "for parts": Condition.FOR_PARTS,
            "piese": Condition.FOR_PARTS,
            "defect": Condition.FOR_PARTS,
        }
        for key, value in mapping.items():
            if key in text:
                return value.value
        return Condition.UNKNOWN.value

    async def _goto(self, page, url: str) -> bool:
        """Navigate with a soft failure (returns False instead of raising)."""
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await jitter(1.0, 3.0)
            return True
        except Exception as exc:
            logger.warning("[%s] navigation to %s failed: %s", self.name, url, exc)
            return False
