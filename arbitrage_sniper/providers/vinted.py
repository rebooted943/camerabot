"""Vinted provider.

Vinted exposes a JSON catalog API but guards it with Datadome. The reliable
trick is to load the site in a stealth browser first (so the anti-bot cookies
are minted), then call the internal API from within the page context using the
already-authenticated session.
"""

from __future__ import annotations

import logging
import urllib.parse

from ..browser import jitter
from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.vinted")


class VintedProvider(BaseProvider):
    name = "vinted"
    label = "Vinted (EU)"
    requires_browser = True

    # vinted.ro is the RO storefront; the catalog API path is shared EU-wide.
    BASE = "https://www.vinted.ro"

    def _api_url(self, query: str, per_page: int) -> str:
        params = {
            "search_text": query,
            "order": "price_low_to_high",
            "per_page": per_page,
            "page": 1,
        }
        return f"{self.BASE}/api/v2/catalog/items?{urllib.parse.urlencode(params)}"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            # 1. Warm up the session so Datadome cookies are set.
            if not await self._goto(page, self.BASE):
                return []
            await jitter(1.5, 3.5)

            # 2. Call the internal API from inside the page (uses session cookies).
            url = self._api_url(query, min(self.max_items, 96))
            try:
                data = await page.evaluate(
                    """async (url) => {
                        const r = await fetch(url, {
                            headers: {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
                            credentials: 'include'
                        });
                        if (!r.ok) return {error: r.status};
                        return await r.json();
                    }""",
                    url,
                )
            except Exception as exc:
                logger.warning("[vinted] in-page fetch failed: %s", exc)
                return []

            if not isinstance(data, dict) or "items" not in data:
                logger.debug("[vinted] unexpected payload: %s", str(data)[:200])
                return []

            return self._parse_items(data["items"])

    def _parse_items(self, raw_items: list) -> list[Item]:
        items: list[Item] = []
        for raw in raw_items or []:
            try:
                price_obj = raw.get("price") or {}
                amount = price_obj.get("amount") if isinstance(price_obj, dict) else price_obj
                price = parse_price(amount)
                currency = (price_obj.get("currency_code") if isinstance(price_obj, dict) else None) or "EUR"

                photo = raw.get("photo") or {}
                image = photo.get("url") if isinstance(photo, dict) else None

                user = raw.get("user") or {}
                seller = user.get("login") if isinstance(user, dict) else None

                items.append(
                    Item(
                        id=str(raw.get("id") or ""),
                        title=str(raw.get("title") or ""),
                        price=price or 0.0,
                        link=str(raw.get("url") or ""),
                        platform=self.name,
                        condition=self.normalise_condition(raw.get("status")),
                        image_url=image,
                        currency=currency,
                        seller_name=seller,
                    )
                )
            except Exception:
                continue
        return items
