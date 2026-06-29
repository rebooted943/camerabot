"""Subito.it provider (Italy's main classifieds platform).

Strategy:
  1. Warm session on subito.it, then call the internal Hades search API.
  2. Fall back to ``__NEXT_DATA__`` embedded in the search page.
  3. Fall back to DOM scraping of the listing grid.
"""

from __future__ import annotations

import logging
import urllib.parse
from typing import Any

from ..browser import jitter
from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.subito")


class SubitoProvider(BaseProvider):
    name = "subito"
    label = "Subito.it"
    requires_browser = True

    BASE = "https://www.subito.it"
    API = "https://hades.subito.it/v1/search/items"

    def _search_url(self, query: str) -> str:
        params = {
            "q": query.strip(),
            "order": "priceasc",
        }
        return f"{self.BASE}/annunci?{urllib.parse.urlencode(params)}"

    def _api_url(self, query: str, limit: int) -> str:
        params = {
            "q": query.strip(),
            "lim": limit,
            "start": 0,
            "order": "priceasc",
        }
        return f"{self.API}?{urllib.parse.urlencode(params)}"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            if not await self._goto(page, self._search_url(query)):
                return []
            await jitter(1.0, 2.5)

            data = await self._in_page_fetch(page, self._api_url(query, self.max_items))
            items = self._from_api(data)
            if items:
                return items

            next_data = await self._next_data(page)
            items = self._from_next_data(next_data)
            if items:
                return items

            return await self._from_dom(page)

    def _from_api(self, data: Any) -> list[Item]:
        if not isinstance(data, dict):
            return []
        ads = data.get("ads") or data.get("items") or data.get("list") or []
        if not isinstance(ads, list):
            return []
        items: list[Item] = []
        for ad in ads:
            item = self._ad_to_item(ad)
            if item:
                items.append(item)
        return items

    def _from_next_data(self, data: dict | None) -> list[Item]:
        if not data:
            return []
        ads: list[dict] = []
        try:
            props = data.get("props", {}).get("pageProps", {})
            for key in ("initialState", "search", "listing"):
                node = props.get(key)
                if isinstance(node, dict):
                    inner = node.get("items") or node.get("ads") or node.get("list")
                    if isinstance(inner, list) and inner:
                        ads = inner
                        break
            if not ads:
                ads = self._dig_ads(data)
        except Exception:
            return []

        items: list[Item] = []
        for ad in ads:
            item = self._ad_to_item(ad)
            if item:
                items.append(item)
        return items

    @staticmethod
    def _dig_ads(data: dict) -> list[dict]:
        """Walk the Next.js tree looking for ad-shaped dict lists."""
        found: list[dict] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key in ("ads", "items", "list"):
                    val = node.get(key)
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        if val[0].get("subject") or val[0].get("title") or val[0].get("urn"):
                            found.extend(val)
                            return
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
        return found

    def _ad_to_item(self, ad: dict[str, Any]) -> Item | None:
        title = ad.get("subject") or ad.get("title")
        if not title:
            return None

        ad_id = str(ad.get("id") or ad.get("urn") or "")
        url = ad.get("urls", {}).get("default") if isinstance(ad.get("urls"), dict) else None
        url = url or ad.get("url") or ad.get("link") or ""
        if url and not str(url).startswith("http"):
            url = self.BASE + str(url)

        price = None
        features = ad.get("features") or {}
        if isinstance(features, dict):
            price = parse_price(str(features.get("/price") or features.get("price") or ""))
        if price is None:
            price_obj = ad.get("price") or {}
            if isinstance(price_obj, dict):
                price = parse_price(price_obj.get("value") or price_obj.get("amount"))
            else:
                price = parse_price(price_obj)

        images = ad.get("images") or []
        image_url = None
        if images and isinstance(images, list):
            first = images[0]
            if isinstance(first, dict):
                image_url = first.get("cdnBaseUrl") or first.get("url")
            else:
                image_url = str(first)

        location = None
        geo = ad.get("geo") or ad.get("location") or {}
        if isinstance(geo, dict):
            parts = [geo.get("city"), geo.get("region"), geo.get("town", {}).get("value")]
            location = ", ".join(p for p in parts if p)

        return Item(
            id=ad_id,
            title=str(title).strip(),
            price=float(price) if price else 0.0,
            link=str(url),
            platform=self.name,
            condition=self.normalise_condition(
                str(features.get("/condition") or features.get("condition") or "")
            ),
            image_url=image_url,
            currency="EUR",
            description=str(ad.get("body") or ad.get("description") or ""),
            location=location,
        )

    async def _from_dom(self, page) -> list[Item]:
        cards = await page.query_selector_all(
            'article[data-testid="listing-card"], article[class*="ItemCard"], a[href*=".htm"]'
        )
        items: list[Item] = []
        seen: set[str] = set()
        for card in cards:
            try:
                link_el = card if await card.get_attribute("href") else await card.query_selector("a")
                href = await link_el.get_attribute("href") if link_el else None
                if not href or href in seen:
                    continue
                seen.add(href)
                if not href.startswith("http"):
                    href = self.BASE + href

                title_el = await card.query_selector("h2, h3, [class*='title'], [class*='Title']")
                title = (await title_el.inner_text()) if title_el else (await card.inner_text())

                price_el = await card.query_selector("[class*='price'], [class*='Price']")
                price_txt = (await price_el.inner_text()) if price_el else ""

                img_el = await card.query_selector("img")
                img = await img_el.get_attribute("src") if img_el else None

                title = (title or "").strip()
                if not title or len(title) < 3:
                    continue
                items.append(
                    Item(
                        id="",
                        title=title[:140],
                        price=parse_price(price_txt) or 0.0,
                        link=href,
                        platform=self.name,
                        image_url=img,
                        currency="EUR",
                    )
                )
            except Exception:
                continue
        return items
