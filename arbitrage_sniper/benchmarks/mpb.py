"""MPB primary benchmark (floor / safety price).

MPB (mpb.com/en-eu) publishes the price at which it *buys* gear in a given
grade. We read the "Sell" / trade-in price for Excellent/Good condition; that
is the risk-zero exit value that anchors the arbitrage trigger.

``thresholds.json`` provides, per target, either a direct MPB product URL/slug
(``mpb_id``) or a search query, plus an optional hard-coded ``mpb_floor`` that
acts as a manual override / fallback when scraping fails.
"""

from __future__ import annotations

import logging
import re
import urllib.parse

from ..browser import jitter
from ..models import Benchmark, parse_price
from .base import BaseBenchmark

logger = logging.getLogger("arbitrage_sniper.benchmarks.mpb")


class MpbBenchmark(BaseBenchmark):
    name = "mpb"

    BASE = "https://www.mpb.com/en-eu"

    def _product_url(self, mpb_id: str) -> str:
        if mpb_id.startswith("http"):
            return mpb_id
        return f"{self.BASE}/product/{mpb_id.strip('/')}"

    def _search_url(self, query: str) -> str:
        return f"{self.BASE}/search?q={urllib.parse.quote_plus(query)}"

    async def _lookup(self, key: str, *, mpb_id: str | None = None, mpb_floor: float | None = None, **_) -> Benchmark:
        # 1. Manual override wins (operator-supplied known-good floor).
        if mpb_floor:
            return Benchmark(
                source=self.name,
                value=float(mpb_floor),
                note="manual floor from thresholds.json",
            )

        # 2. Scrape MPB.
        url = self._product_url(mpb_id) if mpb_id else self._search_url(key)
        async with self.browser.context() as page:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await jitter(1.5, 3.0)
            except Exception as exc:
                logger.warning("[mpb] navigation failed: %s", exc)
                return Benchmark(source=self.name, value=None, url=url, note="nav failed")

            price = await self._extract_sell_price(page)
            return Benchmark(
                source=self.name,
                value=price,
                url=url,
                note="scraped sell/trade-in price" if price else "price not found",
            )

    async def _extract_sell_price(self, page) -> float | None:
        # MPB shows trade-in/sell values; try a few likely selectors then regex.
        selectors = [
            '[data-testid*="sell-price"]',
            '[data-testid*="trade"]',
            '.product-sell-price',
            '[class*="SellPrice"]',
            '[class*="sellPrice"]',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    txt = await el.inner_text()
                    price = parse_price(txt)
                    if price:
                        return price
            except Exception:
                continue

        # Fallback: look for "We'll pay you" / "Sell for" patterns in the text.
        try:
            body = await page.inner_text("body")
        except Exception:
            return None
        for pattern in (
            r"(?:we'?ll pay you|sell for|trade in for)[^\d]{0,20}([\d.,]+)",
            r"\u20ac\s*([\d.,]+)",
        ):
            m = re.search(pattern, body, re.IGNORECASE)
            if m:
                price = parse_price(m.group(1))
                if price:
                    return price
        return None
