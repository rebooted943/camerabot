"""Vinted provider — all EU storefronts (Western + Eastern Europe).

Each country domain exposes the same ``/api/v2/catalog/items`` JSON API but
requires its own Datadome-warmed session. We visit every active storefront in
one browser context, merge results, and return the cheapest listings overall
(prices compared in EUR).
"""

from __future__ import annotations

import logging
import urllib.parse

from ..browser import jitter
from ..config import settings
from ..currency import to_eur
from ..models import Item, parse_price
from .base import BaseProvider
from .vinted_markets import VintedStorefront, active_storefronts

logger = logging.getLogger("arbitrage_sniper.providers.vinted")


class VintedProvider(BaseProvider):
    name = "vinted"
    label = "Vinted (EU)"
    requires_browser = True

    def _api_url(self, storefront: VintedStorefront, query: str, per_page: int) -> str:
        params = {
            "search_text": query,
            "order": "price_low_to_high",
            "per_page": per_page,
            "page": 1,
        }
        return f"{storefront.base_url}/api/v2/catalog/items?{urllib.parse.urlencode(params)}"

    def _storefronts(self) -> list[VintedStorefront]:
        return active_storefronts(
            regions=settings.vinted_regions,
            markets=settings.vinted_markets,
        )

    async def search(self, query: str) -> list[Item]:
        storefronts = self._storefronts()
        if not storefronts:
            logger.warning("[vinted] no storefronts selected (check VINTED_REGIONS / VINTED_MARKETS)")
            return []

        # Pull a small batch from each market, then keep the global cheapest.
        per_store = min(20, max(6, self.max_items))
        items: list[Item] = []
        seen_keys: set[str] = set()

        async with self.browser.context() as page:
            for sf in storefronts:
                batch = await self._search_storefront(page, sf, query, per_store)
                for it in batch:
                    if it.unique_key in seen_keys:
                        continue
                    seen_keys.add(it.unique_key)
                    items.append(it)

        items.sort(key=lambda i: to_eur(i.price, i.currency))
        logger.info(
            "[vinted] merged %d items from %d storefront(s) (%s)",
            len(items),
            len(storefronts),
            ",".join(s.code for s in storefronts),
        )
        return items[: self.max_items]

    async def _search_storefront(
        self,
        page,
        storefront: VintedStorefront,
        query: str,
        per_page: int,
    ) -> list[Item]:
        if not await self._goto(page, storefront.base_url):
            return []
        await jitter(1.0, 2.5)

        url = self._api_url(storefront, query, min(per_page, 96))
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
            logger.warning("[vinted] fetch failed (%s): %s", storefront.code, exc)
            return []

        if not isinstance(data, dict) or "items" not in data:
            logger.debug("[vinted] bad payload from %s: %s", storefront.code, str(data)[:200])
            return []

        parsed = self._parse_items(data["items"], storefront)
        logger.info("[%s/%s] '%s' -> %d items", self.name, storefront.code, query, len(parsed))
        return parsed

    def _parse_items(self, raw_items: list, storefront: VintedStorefront) -> list[Item]:
        items: list[Item] = []
        for raw in raw_items or []:
            try:
                price_obj = raw.get("price") or {}
                amount = price_obj.get("amount") if isinstance(price_obj, dict) else price_obj
                price = parse_price(amount)
                currency = (
                    price_obj.get("currency_code") if isinstance(price_obj, dict) else None
                ) or storefront.currency

                photo = raw.get("photo") or {}
                image = photo.get("url") if isinstance(photo, dict) else None

                user = raw.get("user") or {}
                seller = user.get("login") if isinstance(user, dict) else None

                raw_id = str(raw.get("id") or "")
                link = str(raw.get("url") or "")
                if link and not link.startswith("http"):
                    link = storefront.base_url.rstrip("/") + (
                        link if link.startswith("/") else "/" + link
                    )

                items.append(
                    Item(
                        id=f"{storefront.code}:{raw_id}" if raw_id else "",
                        title=str(raw.get("title") or ""),
                        price=price or 0.0,
                        link=link,
                        platform=self.name,
                        condition=self.normalise_condition(raw.get("status")),
                        image_url=image,
                        currency=currency,
                        seller_name=seller,
                        location=f"{storefront.label} ({storefront.code.upper()})",
                    )
                )
            except Exception:
                continue
        return items
