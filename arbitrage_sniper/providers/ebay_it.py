"""eBay.it buy-side provider (active listings, cheapest first).

Complements the eBay *sold* benchmark: here we scrape live listings that you
could actually buy today on the Italian marketplace.
"""

from __future__ import annotations

import logging
import urllib.parse

from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.ebay_it")


class EbayItProvider(BaseProvider):
    name = "ebay_it"
    label = "eBay.it"
    requires_browser = True

    BASE = "https://www.ebay.it"

    def _search_url(self, query: str) -> str:
        params = {
            "_nkw": query.strip(),
            "_sop": 15,  # price + shipping, lowest first
            "LH_BIN": 1,  # buy-it-now only (actionable listings)
            "rt": "nc",
        }
        return f"{self.BASE}/sch/i.html?{urllib.parse.urlencode(params)}"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            if not await self._goto(page, self._search_url(query)):
                return []

            cards = await page.query_selector_all("li.s-item, .s-item")
            items: list[Item] = []
            for card in cards:
                try:
                    title_el = await card.query_selector(".s-item__title")
                    title = (await title_el.inner_text()) if title_el else ""
                    if not title or "shop on ebay" in title.lower():
                        continue

                    link_el = await card.query_selector("a.s-item__link, a[href*='/itm/']")
                    href = await link_el.get_attribute("href") if link_el else None
                    if not href:
                        continue

                    price_el = await card.query_selector(".s-item__price")
                    price_txt = (await price_el.inner_text()) if price_el else ""
                    if " to " in price_txt.lower() or " a " in price_txt.lower():
                        continue

                    img_el = await card.query_selector("img.s-item__image-img, img")
                    img = await img_el.get_attribute("src") if img_el else None

                    ad_id = ""
                    if "/itm/" in href:
                        ad_id = href.split("/itm/")[-1].split("?")[0]

                    items.append(
                        Item(
                            id=ad_id,
                            title=title.strip(),
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
