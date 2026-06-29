"""Facebook Marketplace provider (Italy + Romania).

Facebook embeds listings as JSON inside script tags (``MarketplaceProductItem``).
We walk that tree after loading city-scoped search pages. Without a logged-in
session Facebook often shows a login wall — set ``FACEBOOK_COOKIES_PATH`` to a
Playwright-exported cookies JSON file for reliable results.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from pathlib import Path
from typing import Any

from ..browser import jitter
from ..config import settings
from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.facebook")

# City-scoped searches covering Italy and Romania.
_SEARCH_LOCATIONS: list[tuple[str, str]] = [
    ("rome", "IT"),
    ("milano", "IT"),
    ("bucharest", "RO"),
    ("cluj-napoca", "RO"),
]

_EXTRACT_JS = """
() => {
    const TYPES = new Set([
        "MarketplaceProductItem",
        "GroupCommerceProductItem",
        "MarketplaceListingRenderable",
    ]);
    const found = [];
    const seen = new Set();

    function walk(node) {
        if (!node || typeof node !== "object") return;
        if (Array.isArray(node)) {
            for (const v of node) walk(v);
            return;
        }
        const tn = node.__typename;
        if (tn && TYPES.has(tn)) {
            const id = node.id || node.listing_id || node.legacy_id;
            if (id && !seen.has(id)) {
                seen.add(id);
                found.push(node);
            }
        }
        for (const v of Object.values(node)) walk(v);
    }

    for (const script of document.querySelectorAll("script")) {
        const txt = script.textContent || "";
        if (!txt.includes("Marketplace") && !txt.includes("marketplace")) continue;
        try {
            if (txt.trim().startsWith("{")) {
                walk(JSON.parse(txt));
                continue;
            }
            for (const m of txt.matchAll(/\\{[^{}]*"__typename"\\s*:\\s*"Marketplace[^"]*"[^{}]*\\}/g)) {
                try { walk(JSON.parse(m[0])); } catch (e) {}
            }
        } catch (e) {}
        const big = txt.match(/\\{"require":\\[\\[.*?\\]\\]\\}/);
        if (big) {
            try { walk(JSON.parse(big[0])); } catch (e) {}
        }
    }
    return found;
}
"""


class FacebookMarketplaceProvider(BaseProvider):
    name = "facebook"
    label = "Facebook Marketplace"
    requires_browser = True

    BASE = "https://www.facebook.com"

    def _search_url(self, city: str, query: str) -> str:
        params = {"query": query.strip()}
        return f"{self.BASE}/marketplace/{city}/search/?{urllib.parse.urlencode(params)}"

    async def search(self, query: str) -> list[Item]:
        if not settings.facebook_cookies_path:
            logger.info("[facebook] skipped (no FACEBOOK_COOKIES_PATH)")
            return []

        items: list[Item] = []
        seen_keys: set[str] = set()

        async with self.browser.context() as page:
            await self._maybe_load_cookies(page)

            for city, country in _SEARCH_LOCATIONS:
                url = self._search_url(city, query)
                if not await self._goto(page, url):
                    continue
                await jitter(2.0, 4.0)

                batch = await self._extract_listings(page, country)
                if not batch:
                    batch = await self._from_dom(page, country)

                for it in batch:
                    if it.unique_key in seen_keys:
                        continue
                    seen_keys.add(it.unique_key)
                    items.append(it)

                if len(items) >= self.max_items:
                    break

        return items[: self.max_items]

    async def _maybe_load_cookies(self, page) -> None:
        path = settings.facebook_cookies_path
        if not path:
            return
        cookie_file = Path(path)
        if not cookie_file.is_file():
            logger.warning("[facebook] cookies file not found: %s", path)
            return
        try:
            raw = json.loads(cookie_file.read_text(encoding="utf-8"))
            cookies = raw if isinstance(raw, list) else raw.get("cookies", [])
            if cookies:
                await page.context.add_cookies(cookies)
                logger.info("[facebook] loaded %d cookies", len(cookies))
        except Exception as exc:
            logger.warning("[facebook] failed to load cookies: %s", exc)

    async def _extract_listings(self, page, country: str) -> list[Item]:
        try:
            raw_list = await page.evaluate(_EXTRACT_JS)
        except Exception as exc:
            logger.debug("[facebook] JSON extract failed: %s", exc)
            return []

        items: list[Item] = []
        for node in raw_list or []:
            item = self._node_to_item(node, country)
            if item:
                items.append(item)
        return items

    def _node_to_item(self, node: dict[str, Any], country: str) -> Item | None:
        title = (
            node.get("marketplace_listing_title")
            or node.get("title")
            or node.get("name")
        )
        if not title:
            return None

        ad_id = str(node.get("id") or node.get("listing_id") or node.get("legacy_id") or "")
        link = f"{self.BASE}/marketplace/item/{ad_id}/" if ad_id else self.BASE

        price = None
        currency = "EUR"
        price_obj = node.get("listing_price") or node.get("formatted_price") or node.get("price")
        if isinstance(price_obj, dict):
            price = parse_price(
                price_obj.get("formatted_amount")
                or price_obj.get("amount")
                or price_obj.get("amount_with_offset")
            )
            currency = price_obj.get("currency") or currency
        else:
            price = parse_price(price_obj)

        if country == "RO" and price and "lei" in str(price_obj).lower():
            currency = "RON"

        image_url = None
        photo = node.get("primary_listing_photo") or node.get("listing_photo") or {}
        if isinstance(photo, dict):
            img = photo.get("image") or photo
            if isinstance(img, dict):
                image_url = img.get("uri") or img.get("url")

        location = None
        loc = node.get("location") or {}
        if isinstance(loc, dict):
            geo = loc.get("reverse_geocode") or loc
            if isinstance(geo, dict):
                location = geo.get("city") or geo.get("city_page") or geo.get("state")

        return Item(
            id=ad_id,
            title=str(title).strip(),
            price=float(price) if price else 0.0,
            link=link,
            platform=self.name,
            image_url=image_url,
            currency=currency,
            location=str(location) if location else country,
        )

    async def _from_dom(self, page, country: str) -> list[Item]:
        """Fallback: scrape visible marketplace item links from the rendered grid."""
        cards = await page.query_selector_all('a[href*="/marketplace/item/"]')
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

                ad_id = href.split("/marketplace/item/")[-1].split("/")[0].split("?")[0]

                aria = await card.get_attribute("aria-label") or ""
                title = aria or (await card.inner_text()) or ""
                title = title.strip()
                if not title:
                    continue

                price_el = await card.query_selector("span[class*='price'], span[class*='Price']")
                price_txt = (await price_el.inner_text()) if price_el else ""
                if not price_txt and "€" in title:
                    price_txt = title

                currency = "RON" if country == "RO" and "lei" in title.lower() else "EUR"
                items.append(
                    Item(
                        id=ad_id,
                        title=title[:140],
                        price=parse_price(price_txt) or 0.0,
                        link=href,
                        platform=self.name,
                        currency=currency,
                        location=country,
                    )
                )
            except Exception:
                continue
        return items
