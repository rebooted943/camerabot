#!/usr/bin/env python3
"""ArbitrageSniper entrypoint.

Pipeline per scheduled run:
    1. Load targets from thresholds.json.
    2. For each target: scrape every buy-side provider (OLX, Vinted, ...).
    3. Drop ads already in seen_ads.db (de-dup) and normalise prices to EUR.
    4. Fetch MPB (floor), eBay-sold + F64 (retail) benchmarks (cached per target).
    5. Trigger rule: buy_price <= mpb_price * MPB_MARGIN  -> build Alert.
    6. Notify via Telegram and record everything in SQLite.

Designed to be run headless from GitHub Actions every 10-15 minutes; the DB is
committed back to the repo by the workflow to persist de-dup state.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field

from arbitrage_sniper import arbitrage
from arbitrage_sniper.benchmarks import EbayBenchmark, F64Benchmark, MpbBenchmark
from arbitrage_sniper.browser import BrowserManager
from arbitrage_sniper.config import THRESHOLDS_PATH, settings
from arbitrage_sniper.currency import to_eur
from arbitrage_sniper.database import Database
from arbitrage_sniper.models import Item
from arbitrage_sniper.notifier import TelegramNotifier
from arbitrage_sniper.providers import ALL_PROVIDERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("arbitrage_sniper.main")


@dataclass
class Target:
    label: str
    queries: list[str]
    mpb_id: str | None = None
    mpb_floor: float | None = None
    ebay_query: str | None = None
    f64_query: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def primary_query(self) -> str:
        return self.queries[0] if self.queries else self.label

    @classmethod
    def from_dict(cls, d: dict) -> "Target":
        return cls(
            label=d["label"],
            queries=d.get("queries") or [d["label"]],
            mpb_id=d.get("mpb_id"),
            mpb_floor=d.get("mpb_floor"),
            ebay_query=d.get("ebay_query"),
            f64_query=d.get("f64_query"),
            extra={k: v for k, v in d.items() if k not in {
                "label", "queries", "mpb_id", "mpb_floor", "ebay_query", "f64_query"
            }},
        )


def load_targets(path=THRESHOLDS_PATH) -> list[Target]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [Target.from_dict(t) for t in data.get("targets", [])]


def normalise_to_eur(item: Item) -> Item:
    """Convert an item's price to EUR in-place and return it."""
    if item.currency and item.currency.upper() != "EUR":
        item.price = to_eur(item.price, item.currency)
        item.currency = "EUR"
    return item


class Sniper:
    def __init__(self, browser: BrowserManager) -> None:
        self.browser = browser
        self.providers = [P(browser) for P in ALL_PROVIDERS]
        self.mpb = MpbBenchmark(browser)
        self.ebay = EbayBenchmark(browser)
        self.f64 = F64Benchmark(browser)
        self.notifier = TelegramNotifier()

    async def collect_items(self, target: Target) -> list[Item]:
        items: list[Item] = []
        seen_keys: set[str] = set()
        for provider in self.providers:
            for query in target.queries:
                results = await provider.safe_search(query)
                for it in results:
                    if it.unique_key in seen_keys:
                        continue
                    seen_keys.add(it.unique_key)
                    items.append(it)
        return items

    async def fetch_benchmarks(self, target: Target):
        mpb = await self.mpb.get(
            target.primary_query, mpb_id=target.mpb_id, mpb_floor=target.mpb_floor
        )
        ebay = await self.ebay.get(target.ebay_query or target.primary_query)
        f64 = await self.f64.get(target.f64_query or target.primary_query)
        return mpb, ebay, f64

    async def process_target(self, target: Target, db: Database) -> tuple[int, int, int]:
        logger.info("=== target: %s ===", target.label)
        all_items = await self.collect_items(target)
        scanned = len(all_items)

        # De-dup against SQLite, then normalise prices to EUR.
        new_items = db.filter_new(all_items)
        for it in new_items:
            normalise_to_eur(it)
        logger.info("%s: %d scanned, %d new", target.label, scanned, len(new_items))

        if not new_items:
            return scanned, 0, 0

        mpb, ebay, f64 = await self.fetch_benchmarks(target)
        logger.info(
            "%s benchmarks | mpb=%s ebay=%s f64=%s",
            target.label, mpb.value, ebay.value, f64.value,
        )

        alerts = 0
        for it in new_items:
            alert = arbitrage.evaluate(
                it, target_label=target.label, mpb=mpb, ebay=ebay, f64=f64
            )
            if alert:
                if not settings.dry_run:
                    await self.notifier.send_alert(alert)
                db.record_alert(alert)
                alerts += 1
            else:
                db.record_item(it)
        return scanned, len(new_items), alerts

    async def run(self, db: Database) -> tuple[int, int, int]:
        targets = load_targets()
        logger.info("loaded %d targets", len(targets))
        total_scanned = total_new = total_alerts = 0
        for target in targets:
            try:
                s, n, a = await self.process_target(target, db)
            except Exception as exc:
                logger.exception("target '%s' failed: %s", target.label, exc)
                continue
            total_scanned += s
            total_new += n
            total_alerts += a
        return total_scanned, total_new, total_alerts


async def amain(args: argparse.Namespace) -> int:
    problems = settings.validate()
    for p in problems:
        logger.warning("config: %s", p)

    if args.dry_run or settings.dry_run:
        notifier = TelegramNotifier()
        ok = await notifier.send_text("\u2705 ArbitrageSniper dry-run ping: bot is alive.")
        logger.info("dry-run ping sent=%s", ok)
        return 0

    db = Database()
    run_id = db.start_run()
    scanned = new_ads = alerts = 0
    try:
        async with BrowserManager() as browser:
            sniper = Sniper(browser)
            scanned, new_ads, alerts = await sniper.run(db)
    finally:
        db.finish_run(run_id, scanned=scanned, new_ads=new_ads, alerts=alerts)
        logger.info(
            "run done | scanned=%d new=%d alerts=%d | stats=%s",
            scanned, new_ads, alerts, db.stats(),
        )
        db.close()

    if alerts and not settings.dry_run:
        # optional heartbeat summary
        if args.summary:
            await TelegramNotifier().send_summary(scanned=scanned, new_ads=new_ads, alerts=alerts)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ArbitrageSniper - used-gear arbitrage scanner")
    parser.add_argument("--dry-run", action="store_true", help="send a Telegram ping and exit")
    parser.add_argument("--summary", action="store_true", help="send a run summary to Telegram")
    args = parser.parse_args()
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
