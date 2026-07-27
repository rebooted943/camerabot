"""On-demand scan runner for the dashboard "Scan now" button.

Runs a single scan in the background (one at a time) using the same engine as
the CLI/Action. Requires Playwright + Chromium to be installed locally; if they
are missing the failure is surfaced in the status so the UI can show it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from ..browser import BrowserManager
from ..database import Database

logger = logging.getLogger("arbitrage_sniper.web.scan")


class ScanRunner:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self.status: dict = {"state": "idle"}

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def snapshot(self) -> dict:
        return dict(self.status)

    def start(
        self,
        *,
        mode: str = "all",
        query: Optional[str] = None,
        providers: Optional[list[str]] = None,
    ) -> tuple[bool, str]:
        if self.running:
            return False, "a scan is already running"
        self.status = {
            "state": "running",
            "mode": mode,
            "query": query,
            "providers": providers,
            "message": "starting\u2026",
            "started_at": int(time.time()),
            "finished_at": None,
            "scanned": 0,
            "new": 0,
            "alerts": 0,
            "error": None,
        }
        self._task = asyncio.create_task(self._run(mode, query, providers))
        return True, "scan started"

    async def _run(self, mode: str, query: Optional[str], providers: Optional[list[str]]) -> None:
        try:
            import main  # lazy import (repo-root module) to reuse the engine

            self.status["message"] = "launching browser\u2026"
            db = Database()
            try:
                async with BrowserManager() as browser:
                    sniper = main.Sniper(browser, provider_names=providers)
                    self.status["message"] = "scraping providers + benchmarks\u2026"
                    if mode == "query" and query:
                        r = await sniper.scan_query(query, db)
                        scanned, new, alerts = r.scanned, r.new_ads, len(r.alerts)
                    else:
                        scanned, new, alerts = await sniper.scan_all(db)
                self.status.update(scanned=scanned, new=new, alerts=alerts)
            finally:
                db.close()
            self.status.update(
                state="done", message="completed", finished_at=int(time.time())
            )
            logger.info("scan done: %s", self.status)
        except Exception as exc:  # pragma: no cover - runtime/browser errors
            logger.exception("scan failed")
            self.status.update(
                state="error",
                message="failed \u2014 is Playwright installed? (python -m playwright install chromium)",
                error=str(exc),
                finished_at=int(time.time()),
            )


runner = ScanRunner()
