"""Back Market provider (refurbished electronics across EU storefronts).

Uses the Italian storefront by default; prices are in EUR. We scrape the search
results page (Back Market exposes product cards with grade-based pricing).
"""

from __future__ import annotations

import logging
import urllib.parse

from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.backmarket")


class BackmarketProvider(BaseProvider):
    name = "backmarket"
    label = "Back Market"
    requires_browser = True

    BASE = "https://www.backmarket.it"
    SEARCH = "https://www.backmarket.it/it-it/search"

    def _search_url(self, query: str) -> str:
        params = {"q": query.strip(), "sort": "price_asc"}
        return f"{self.SEARCH}?{urllib.parse.urlencode(params)}"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            if not await self._goto(page, self._search_url(query)):
                return []

            # Product cards on Back Market use fairly stable data-test attributes.
            cards = await page.query_selector_all(
                'a[href*="/p/"], [data-qa="product-card"], article[class*="ProductCard"]'
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

                    title_el = await card.query_selector(
                        "h2, h3, [data-qa='product-name'], [class*='ProductTitle']"
                    )
                    title = (await title_el.inner_text()) if title_el else (await card.inner_text())

                    price_el = await card.query_selector(
                        "[data-qa='product-price'], [class*='Price'], [class*='price']"
                    )
                    price_txt = (await price_el.inner_text()) if price_el else ""

                    grade_el = await card.query_selector("[class*='Grade'], [data-qa*='grade']")
                    condition = (await grade_el.inner_text()) if grade_el else ""

                    img_el = await card.query_selector("img")
                    img = await img_el.get_attribute("src") if img_el else None

                    title = (title or "").strip()
                    if not title or len(title) < 3:
                        continue

                    ad_id = href.rstrip("/").split("/")[-1]
                    items.append(
                        Item(
                            id=ad_id,
                            title=title[:140],
                            price=parse_price(price_txt) or 0.0,
                            link=href,
                            platform=self.name,
                            condition=self.normalise_condition(condition),
                            image_url=img,
                            currency="EUR",
                        )
                    )
                except Exception:
                    continue
            return items
