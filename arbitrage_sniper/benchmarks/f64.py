"""F64.ro secondary benchmark (Romanian retailer's used/'Resigilate' section).

Gives a local retail reference. Prices on F64 are in RON, so they are converted
to EUR. We only average products whose *title* matches the target (relevance),
apply hard sanity bounds and take the median - this removes the spurious
readings (e.g. a constant ~25848) caused by grabbing the wrong number on the
page.
"""

from __future__ import annotations

import logging
import urllib.parse

from ..browser import jitter
from ..currency import to_eur
from ..matching import is_relevant
from ..models import Benchmark, parse_price
from .base import BaseBenchmark

logger = logging.getLogger("arbitrage_sniper.benchmarks.f64")


class F64Benchmark(BaseBenchmark):
    name = "f64"

    BASE = "https://www.f64.ro"

    def _search_url(self, query: str) -> str:
        return f"{self.BASE}/cauta?q={urllib.parse.quote_plus(query)}"

    async def _lookup(self, key: str, *, include_terms=None, **_) -> Benchmark:
        url = self._search_url(key)
        if not include_terms:
            from ..matching import auto_include_terms

            include_terms = auto_include_terms(key)

        async with self.browser.context() as page:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await jitter(1.5, 3.0)
            except Exception as exc:
                logger.warning("[f64] nav failed: %s", exc)
                return Benchmark(source=self.name, value=None, url=url, note="nav failed")

            prices_eur: list[float] = []
            matched = 0
            cards = await page.query_selector_all(
                '[data-product-id], .product-box, .product-item, [class*="product-card"]'
            )
            for card in cards:
                try:
                    title_el = await card.query_selector(
                        '[class*="title"], [class*="name"], a[title], h2, h3'
                    )
                    title = ""
                    if title_el:
                        title = (await title_el.get_attribute("title")) or (
                            await title_el.inner_text()
                        )
                    # Skip products that are clearly a different model/accessory.
                    if title and not is_relevant(title, include_terms):
                        continue

                    price_el = await card.query_selector(
                        '[class*="price-now"], [class*="product-price"], .price, [class*="price"]'
                    )
                    if not price_el:
                        continue
                    ron = parse_price(await price_el.inner_text())
                    if not ron:
                        continue
                    eur = to_eur(ron, "RON")
                    prices_eur.append(eur)
                    matched += 1
                except Exception:
                    continue

            value = self._aggregate(prices_eur, lo=10.0, hi=15000.0)
            return Benchmark(
                source=self.name,
                value=value,
                sample_size=matched,
                url=url,
                note=f"F64 used/retail, EUR median of {matched} matched products",
            )
