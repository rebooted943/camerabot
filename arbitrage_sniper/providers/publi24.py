"""Publi24.ro provider (DOM scraping; lighter anti-bot than OLX/Vinted)."""

from __future__ import annotations

import logging
import urllib.parse

from ..models import Item, parse_price
from .base import BaseProvider

logger = logging.getLogger("arbitrage_sniper.providers.publi24")


class Publi24Provider(BaseProvider):
    name = "publi24"
    label = "Publi24.ro"
    requires_browser = True

    BASE = "https://www.publi24.ro"

    def _search_url(self, query: str) -> str:
        slug = urllib.parse.quote_plus(query.strip())
        return f"{self.BASE}/anunturi/?keywords={slug}&sortby=price-asc"

    async def search(self, query: str) -> list[Item]:
        async with self.browser.context() as page:
            if not await self._goto(page, self._search_url(query)):
                return []

            cards = await page.query_selector_all("article.article-listing, .listing-item, .article")
            items: list[Item] = []
            for card in cards:
                try:
                    link_el = await card.query_selector("a")
                    href = await link_el.get_attribute("href") if link_el else None
                    if href and not href.startswith("http"):
                        href = self.BASE + href

                    title_el = await card.query_selector(".article-title, h2, .title")
                    title = (await title_el.inner_text()) if title_el else ""

                    price_el = await card.query_selector(".price, .article-price, [class*=price]")
                    price_txt = (await price_el.inner_text()) if price_el else ""

                    img_el = await card.query_selector("img")
                    img = None
                    if img_el:
                        img = await img_el.get_attribute("src") or await img_el.get_attribute("data-src")

                    if not title or not href:
                        continue
                    items.append(
                        Item(
                            id="",  # fingerprint auto-derived from link+title
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
