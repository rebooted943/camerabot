"""Wallapop.com provider.

Wallapop has a public-ish JSON search API. We mint cookies via the stealth
browser and then query the API from inside the page, mirroring the Vinted flow.
"""

from __future__ import annotations

import logging
import urllib.parse

from ..browser import jitter
from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.wallapop")


class WallapopProvider(BaseProvider):
    name = "wallapop"
    label = "Wallapop"
    requires_browser = True

    BASE = "https://es.wallapop.com"
    API = "https://api.wallapop.com/api/v3/general/search"

    def _api_url(self, query: str) -> str:
        params = {
            "keywords": query,
            "order_by": "price_low_to_high",
            "filters_source": "search_box",
        }
        return f"{self.API}?{urllib.parse.urlencode(params)}"

    def _web_url(self, query: str) -> str:
        return f"{self.BASE}/search?keywords={urllib.parse.quote_plus(query)}"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            if not await self._goto(page, self._web_url(query)):
                return []
            await jitter(1.5, 3.0)

            url = self._api_url(query)
            try:
                data = await page.evaluate(
                    """async (url) => {
                        const r = await fetch(url, {
                            headers: {'Accept': 'application/json'},
                            credentials: 'include'
                        });
                        if (!r.ok) return {error: r.status};
                        return await r.json();
                    }""",
                    url,
                )
            except Exception as exc:
                logger.warning("[wallapop] in-page fetch failed: %s", exc)
                data = None

            objects = self._extract_objects(data)
            if objects:
                return self._parse_api(objects)

            # Fallback: scrape the rendered grid.
            return await self._from_dom(page)

    @staticmethod
    def _extract_objects(data) -> list:
        if not isinstance(data, dict):
            return []
        # API shape: {"search_objects": [...]} or {"data": {"section": {"payload": {"items": [...]}}}}
        if isinstance(data.get("search_objects"), list):
            return data["search_objects"]
        try:
            return data["data"]["section"]["payload"]["items"]
        except (KeyError, TypeError):
            return []

    def _parse_api(self, objects: list) -> list[Item]:
        items: list[Item] = []
        for raw in objects:
            try:
                price = parse_price(raw.get("price"))
                currency = raw.get("currency") or "EUR"
                images = raw.get("images") or []
                image = None
                if images and isinstance(images, list):
                    first = images[0]
                    image = first.get("medium") if isinstance(first, dict) else first
                web_slug = raw.get("web_slug") or raw.get("id")
                link = f"{self.BASE}/item/{web_slug}" if web_slug else self.BASE
                items.append(
                    Item(
                        id=str(raw.get("id") or ""),
                        title=str(raw.get("title") or ""),
                        price=price or 0.0,
                        link=link,
                        platform=self.name,
                        image_url=image,
                        currency=currency,
                        description=str(raw.get("description") or ""),
                    )
                )
            except Exception:
                continue
        return items

    async def _from_dom(self, page) -> list[Item]:
        cards = await page.query_selector_all('a[href*="/item/"]')
        items: list[Item] = []
        seen: set[str] = set()
        for card in cards:
            try:
                href = await card.get_attribute("href")
                if not href or href in seen:
                    continue
                seen.add(href)
                if not href.startswith("http"):
                    href = self.BASE + href
                title = (await card.get_attribute("title")) or (await card.inner_text())
                price_el = await card.query_selector('[class*="price"], [class*="Price"]')
                price_txt = (await price_el.inner_text()) if price_el else ""
                items.append(
                    Item(
                        id="",
                        title=(title or "").strip()[:140],
                        price=parse_price(price_txt) or 0.0,
                        link=href,
                        platform=self.name,
                        currency="EUR",
                    )
                )
            except Exception:
                continue
        return items
