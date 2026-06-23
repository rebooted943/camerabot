"""F64.ro secondary benchmark (Romanian retailer's used/'Resigilate' section).

Gives a local retail reference for the same gear. Used as a complementary
target price next to eBay-sold averages.
"""

from __future__ import annotations

import logging
import urllib.parse

from ..browser import jitter
from ..models import Benchmark, parse_price
from .base import BaseBenchmark

logger = logging.getLogger("arbitrage_sniper.benchmarks.f64")


class F64Benchmark(BaseBenchmark):
    name = "f64"

    BASE = "https://www.f64.ro"

    def _search_url(self, query: str) -> str:
        return f"{self.BASE}/cauta?q={urllib.parse.quote_plus(query)}"

    async def _lookup(self, key: str, **_) -> Benchmark:
        url = self._search_url(key)
        async with self.browser.context() as page:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await jitter(1.5, 3.0)
            except Exception as exc:
                logger.warning("[f64] nav failed: %s", exc)
                return Benchmark(source=self.name, value=None, url=url, note="nav failed")

            prices: list[float] = []
            cards = await page.query_selector_all(
                '[class*="product"], .product-item, [data-product-id]'
            )
            for card in cards:
                try:
                    price_el = await card.query_selector('[class*="price"], .price')
                    if not price_el:
                        continue
                    txt = await price_el.inner_text()
                    p = parse_price(txt)
                    if p:
                        prices.append(p)
                except Exception:
                    continue

            avg = self._avg(prices)
            return Benchmark(
                source=self.name,
                value=avg,
                sample_size=len(prices),
                url=url,
                note=f"F64 used/retail scrape ({len(prices)} samples)",
            )
