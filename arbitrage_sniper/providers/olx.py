"""OLX.ro provider.

OLX sits behind Cloudflare/Datadome, so we drive it with the stealth browser.
We try the JSON embedded in OLX's Next.js ``__NEXT_DATA__`` payload first (most
robust), then fall back to DOM scraping of the listing grid.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any

from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.olx")


class OlxProvider(BaseProvider):
    name = "olx"
    label = "OLX.ro"
    requires_browser = True

    BASE = "https://www.olx.ro"

    def _search_url(self, query: str) -> str:
        slug = urllib.parse.quote(query.strip())
        # Cheapest first to surface arbitrage candidates quickly.
        return f"{self.BASE}/oferte/q-{slug}/?search%5Border%5D=filter_float_price%3Aasc"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            if not await self._goto(page, self._search_url(query)):
                return []

            # Best path: structured Next.js data.
            items = await self._from_next_data(page, query)
            if items:
                return items

            # Fallback: DOM scraping.
            return await self._from_dom(page, query)

    async def _from_next_data(self, page, query: str) -> list[Item]:
        try:
            raw = await page.evaluate(
                "() => { const el = document.getElementById('__NEXT_DATA__');"
                " return el ? el.textContent : null; }"
            )
            if not raw:
                return []
            data = json.loads(raw)
        except Exception as exc:
            logger.debug("[olx] no __NEXT_DATA__: %s", exc)
            return []

        ads = self._dig_for_ads(data)
        items: list[Item] = []
        for ad in ads:
            try:
                item = self._ad_to_item(ad)
                if item:
                    items.append(item)
            except Exception:
                continue
        return items

    @staticmethod
    def _dig_for_ads(data: dict) -> list[dict]:
        """Locate the ad list inside OLX's redux/next state (structure shifts)."""
        try:
            listing = data["props"]["pageProps"]
        except (KeyError, TypeError):
            return []
        for key in ("ads", "data", "listing"):
            node = listing.get(key)
            if isinstance(node, list) and node and isinstance(node[0], dict):
                return node
            if isinstance(node, dict):
                inner = node.get("ads") or node.get("items")
                if isinstance(inner, list):
                    return inner
        return []

    def _ad_to_item(self, ad: dict[str, Any]) -> Item | None:
        title = ad.get("title")
        if not title:
            return None
        url = ad.get("url") or ad.get("link") or ""
        if url and not url.startswith("http"):
            url = self.BASE + url

        price = None
        params = ad.get("params") or []
        if isinstance(params, list):
            for p in params:
                if p.get("key") == "price":
                    val = (p.get("value") or {})
                    price = val.get("value") or parse_price(val.get("label"))
                    break
        if price is None:
            price = parse_price(str(ad.get("price", "")))

        photos = ad.get("photos") or []
        image_url = None
        if photos and isinstance(photos, list):
            first = photos[0]
            image_url = first.get("link") if isinstance(first, dict) else first

        location = None
        loc = ad.get("location") or {}
        if isinstance(loc, dict):
            city = (loc.get("city") or {}).get("name")
            location = city

        return Item(
            id=str(ad.get("id") or ""),
            title=str(title),
            price=float(price) if price else 0.0,
            link=url,
            platform=self.name,
            condition=self.normalise_condition(self._param(ad, "state")),
            image_url=image_url,
            currency="RON",
            description=str(ad.get("description") or ""),
            location=location,
        )

    @staticmethod
    def _param(ad: dict, key: str) -> str | None:
        for p in ad.get("params", []) or []:
            if p.get("key") == key:
                v = p.get("value")
                if isinstance(v, dict):
                    return v.get("label") or v.get("key")
                return v
        return None

    async def _from_dom(self, page, query: str) -> list[Item]:
        cards = await page.query_selector_all('[data-cy="l-card"]')
        items: list[Item] = []
        for card in cards:
            try:
                link_el = await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else None
                if href and not href.startswith("http"):
                    href = self.BASE + href

                title_el = await card.query_selector("h6, h4")
                title = (await title_el.inner_text()) if title_el else ""

                price_el = await card.query_selector('[data-testid="ad-price"]')
                price_txt = (await price_el.inner_text()) if price_el else ""

                img_el = await card.query_selector("img")
                img = await img_el.get_attribute("src") if img_el else None

                ad_id = await card.get_attribute("id") or ""

                if not title or not href:
                    continue
                items.append(
                    Item(
                        id=ad_id,
                        title=title.strip(),
                        price=parse_price(price_txt) or 0.0,
                        link=href,
                        platform=self.name,
                        image_url=img,
                        currency="RON",
                    )
                )
            except Exception:
                continue
        return items
