"""eBay.de secondary benchmark (retail / target price from SOLD items).

Two strategies, in order of preference:
  1. eBay Browse API (if ``EBAY_APP_TOKEN`` is configured) - clean and stable.
  2. Scraping the "Sold/Completed" search results on ebay.de - no creds needed.

The returned value is a trimmed average of recent sold prices: the realistic
resale ceiling and hence the *maximum potential* gain.
"""

from __future__ import annotations

import logging
import urllib.parse

from ..browser import http_client, jitter
from ..config import settings
from ..models import Benchmark, parse_price
from .base import BaseBenchmark

logger = logging.getLogger("arbitrage_sniper.benchmarks.ebay")


class EbayBenchmark(BaseBenchmark):
    name = "ebay"

    BROWSE_API = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    def _sold_url(self, query: str) -> str:
        params = {
            "_nkw": query,
            "LH_Sold": 1,
            "LH_Complete": 1,
            "_sop": 13,  # newest first
        }
        return f"https://www.ebay.de/sch/i.html?{urllib.parse.urlencode(params)}"

    async def _lookup(self, key: str, **_) -> Benchmark:
        if settings.ebay_app_token:
            result = await self._via_api(key)
            if result.available:
                return result
        return await self._via_scrape(key)

    async def _via_api(self, query: str) -> Benchmark:
        headers = {
            "Authorization": f"Bearer {settings.ebay_app_token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE",
            "Accept": "application/json",
        }
        params = {"q": query, "limit": 50, "filter": "conditionIds:{3000|2500|2000}"}
        try:
            async with http_client() as client:
                resp = await client.get(self.BROWSE_API, headers=headers, params=params)
            if resp.status_code != 200:
                logger.warning("[ebay] API %s: %s", resp.status_code, resp.text[:200])
                return Benchmark(source=self.name, value=None, note="api error")
            data = resp.json()
        except Exception as exc:
            logger.warning("[ebay] API call failed: %s", exc)
            return Benchmark(source=self.name, value=None, note="api exception")

        prices: list[float] = []
        for it in data.get("itemSummaries", []) or []:
            price_obj = it.get("price") or {}
            p = parse_price(price_obj.get("value"))
            if p:
                prices.append(p)
        avg = self._avg(prices)
        return Benchmark(
            source=self.name,
            value=avg,
            sample_size=len(prices),
            note=f"Browse API ({len(prices)} active listings)",
        )

    async def _via_scrape(self, query: str) -> Benchmark:
        url = self._sold_url(query)
        async with self.browser.context() as page:
            try:
                await page.goto(url, wait_until="domcontentloaded")
                await jitter(1.5, 3.0)
            except Exception as exc:
                logger.warning("[ebay] scrape nav failed: %s", exc)
                return Benchmark(source=self.name, value=None, url=url, note="nav failed")

            prices: list[float] = []
            cards = await page.query_selector_all("li.s-item, .s-item")
            for card in cards:
                try:
                    price_el = await card.query_selector(".s-item__price")
                    if not price_el:
                        continue
                    txt = await price_el.inner_text()
                    if " to " in txt.lower() or "bis" in txt.lower():
                        continue  # skip ranges
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
                note=f"sold-items scrape ({len(prices)} samples)",
            )
