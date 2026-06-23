"""Async Playwright session manager with stealth, UA rotation and jittered delays.

This is the single anti-bot surface used by every provider/benchmark that needs
a real browser (Vinted, OLX, MPB, ...). Lightweight sources may also use the
plain ``httpx`` client exposed here.
"""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import asynccontextmanager
from typing import Optional

from .config import settings

logger = logging.getLogger("arbitrage_sniper.browser")

# A small pool of realistic, current desktop user agents.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]

LOCALES = ["en-US", "ro-RO", "en-GB", "de-DE"]
VIEWPORTS = [(1920, 1080), (1536, 864), (1440, 900), (1366, 768)]


async def jitter(min_s: Optional[float] = None, max_s: Optional[float] = None) -> None:
    """Sleep a random amount to look human and to be polite to the target site."""
    lo = settings.min_delay if min_s is None else min_s
    hi = settings.max_delay if max_s is None else max_s
    if hi < lo:
        hi = lo
    delay = random.uniform(lo, hi)
    logger.debug("sleeping %.2fs (jitter)", delay)
    await asyncio.sleep(delay)


class BrowserManager:
    """Owns a single Playwright/Chromium instance, hands out stealthy contexts."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        logger.info("browser launched (headless=%s)", settings.headless)

    async def stop(self) -> None:
        try:
            if self._browser:
                await self._browser.close()
        finally:
            if self._playwright:
                await self._playwright.stop()
        logger.info("browser stopped")

    @asynccontextmanager
    async def context(self):
        """Yield a fresh, fingerprint-randomised, stealth-patched page."""
        if self._browser is None:
            raise RuntimeError("BrowserManager not started")

        ua = random.choice(USER_AGENTS)
        width, height = random.choice(VIEWPORTS)
        locale = random.choice(LOCALES)

        ctx = await self._browser.new_context(
            user_agent=ua,
            locale=locale,
            viewport={"width": width, "height": height},
            timezone_id=random.choice(["Europe/Bucharest", "Europe/Berlin", "Europe/Madrid"]),
            extra_http_headers={"Accept-Language": f"{locale},en;q=0.8"},
        )
        ctx.set_default_navigation_timeout(settings.nav_timeout_ms)
        ctx.set_default_timeout(settings.nav_timeout_ms)

        page = await ctx.new_page()
        await self._apply_stealth(page)
        try:
            yield page
        finally:
            await ctx.close()

    @staticmethod
    async def _apply_stealth(page) -> None:
        """Apply playwright-stealth if available, plus a couple of manual patches."""
        applied = False
        try:
            from playwright_stealth import stealth_async  # type: ignore

            await stealth_async(page)
            applied = True
        except Exception:
            # API differs across versions; try the newer class-based entrypoint.
            try:
                from playwright_stealth import Stealth  # type: ignore

                await Stealth().apply_stealth_async(page)
                applied = True
            except Exception:
                applied = False

        if not applied:
            logger.warning("playwright-stealth unavailable; using manual patches only")
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                "window.chrome = { runtime: {} };"
                "Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});"
                "Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});"
            )


@asynccontextmanager
async def http_client(timeout: float = 20.0):
    """Shared async HTTP client for API/lightweight sources (Telegram, eBay API)."""
    import httpx

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        yield client
