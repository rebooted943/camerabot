#!/usr/bin/env python3
"""ArbitrageSniper entrypoint.

Modes:
    python main.py                # scheduled scan of all tracked targets
    python main.py --summary      # ... and post a run summary to Telegram
    python main.py --dry-run      # send a Telegram ping and exit
    python main.py --listen       # process Telegram commands (/scan, /add, ...)
    python main.py --query "..."  # one-off scan for a single query

Pipeline per target:
    1. Scrape every buy-side provider (Subito, eBay.it, Back Market, Facebook
       Marketplace, OLX, Publi24, Vinted EU west+east).
    2. Keep only listings whose title actually matches the target (relevance
       filter: drops grips/batteries/wrong models).
    3. Drop ads already in seen_ads.db and normalise prices to EUR.
    4. Fetch MPB (floor), eBay-sold + F64 (retail) benchmarks (relevance-aware).
    5. Trigger: buy <= mpb * MPB_MARGIN AND gain <= MAX_GAIN_PCT -> alert.
    6. Notify via Telegram and record everything in SQLite (committed by CI).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field

from arbitrage_sniper import arbitrage, commands as cmd
from arbitrage_sniper.benchmarks import EbayBenchmark, F64Benchmark, MpbBenchmark
from arbitrage_sniper.browser import BrowserManager
from arbitrage_sniper.config import settings
from arbitrage_sniper.currency import to_eur
from arbitrage_sniper.database import Database
from arbitrage_sniper.matching import is_relevant
from arbitrage_sniper.models import Alert, Item
from arbitrage_sniper.notifier import TelegramNotifier
from arbitrage_sniper.providers import ALL_PROVIDERS
from arbitrage_sniper.targets import (
    Target,
    add_target,
    list_labels,
    load_targets,
    remove_target,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("arbitrage_sniper.main")


@dataclass
class ScanResult:
    target: Target
    scanned: int = 0
    new_ads: int = 0
    alerts: list[Alert] = field(default_factory=list)
    cheapest: list[Item] = field(default_factory=list)
    mpb: float | None = None
    ebay: float | None = None
    f64: float | None = None


def normalise_to_eur(item: Item) -> Item:
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
        # (provider_name, normalised_query) -> items; avoids re-scraping the same
        # query when multiple targets share it (critical for Vinted EU).
        self._search_cache: dict[tuple[str, str], list[Item]] = {}

    @staticmethod
    def _query_key(query: str) -> str:
        return query.strip().lower()

    async def prefetch_queries(self, targets: list[Target]) -> None:
        """Scrape each provider/query pair once before processing targets."""
        canonical: dict[str, str] = {}
        for target in targets:
            for query in target.queries:
                key = self._query_key(query)
                canonical.setdefault(key, query)

        if not canonical:
            return

        logger.info("prefetch: %d unique queries across %d target(s)", len(canonical), len(targets))
        for provider in self.providers:
            if provider.name == "facebook" and not settings.facebook_cookies_path:
                logger.info("[facebook] skipped prefetch (no FACEBOOK_COOKIES_PATH)")
                for key in canonical:
                    self._search_cache[(provider.name, key)] = []
                continue
            for key, query in canonical.items():
                await self._cached_provider_search(provider, query)

    async def _cached_provider_search(self, provider, query: str) -> list[Item]:
        key = (provider.name, self._query_key(query))
        if key in self._search_cache:
            return self._search_cache[key]
        items = await provider.safe_search(query)
        self._search_cache[key] = items
        return items

    async def collect_items(self, target: Target) -> list[Item]:
        include = target.effective_include
        exclude = target.exclude_terms
        items: list[Item] = []
        seen_keys: set[str] = set()
        for provider in self.providers:
            if provider.name == "facebook" and not settings.facebook_cookies_path:
                continue
            for query in target.queries:
                for it in await self._cached_provider_search(provider, query):
                    if it.unique_key in seen_keys:
                        continue
                    # Relevance filter: skip accessories / wrong models.
                    if not is_relevant(it.title, include, exclude):
                        logger.debug("[%s] drop (irrelevant): %s", provider.name, it.title)
                        continue
                    seen_keys.add(it.unique_key)
                    items.append(it)
        return items

    async def fetch_benchmarks(self, target: Target):
        include = target.effective_include
        mpb = await self.mpb.get(
            target.primary_query, mpb_id=target.mpb_id, mpb_floor=target.mpb_floor
        )
        ebay = await self.ebay.get(target.ebay_query or target.primary_query, include_terms=include)
        f64 = await self.f64.get(target.f64_query or target.primary_query, include_terms=include)
        return mpb, ebay, f64

    async def process_target(self, target: Target, db: Database, *, notify: bool = True) -> ScanResult:
        logger.info("=== target: %s ===", target.label)
        result = ScanResult(target=target)

        all_items = await self.collect_items(target)
        result.scanned = len(all_items)

        new_items = db.filter_new(all_items)
        for it in new_items:
            normalise_to_eur(it)
        result.new_ads = len(new_items)
        logger.info("%s: %d relevant, %d new", target.label, result.scanned, result.new_ads)

        # Cheapest relevant listings (useful for ad-hoc replies even w/o trigger).
        result.cheapest = sorted(new_items, key=lambda i: i.price)[:3]

        if not new_items:
            return result

        mpb, ebay, f64 = await self.fetch_benchmarks(target)
        result.mpb, result.ebay, result.f64 = mpb.value, ebay.value, f64.value
        logger.info(
            "%s benchmarks | mpb=%s ebay=%s f64=%s",
            target.label, mpb.value, ebay.value, f64.value,
        )

        for it in new_items:
            alert = arbitrage.evaluate(
                it, target_label=target.label, mpb=mpb, ebay=ebay, f64=f64
            )
            if alert:
                delivered = True
                if notify and not settings.dry_run:
                    delivered = await self.notifier.send_alert(
                        alert,
                        chat_id=target.chat_id,
                        message_thread_id=target.topic_id,
                    )
                if delivered:
                    db.record_alert(alert)
                    result.alerts.append(alert)
                else:
                    # Delivery failed: do NOT mark the ad as seen/alerted, so the
                    # next run re-evaluates and retries it instead of silently
                    # dropping the deal (this is the "alerts: 1 but no post" bug).
                    logger.error(
                        "alert delivery FAILED for %s; left unseen for retry",
                        it.unique_key,
                    )
            else:
                # Record even non-triggering ads so they are never re-evaluated
                # / re-notified on subsequent runs.
                db.record_item(it)
        return result

    async def scan_all(self, db: Database) -> tuple[int, int, int]:
        targets = load_targets()
        logger.info("loaded %d targets", len(targets))
        await self.prefetch_queries(targets)
        s = n = a = 0
        for target in targets:
            try:
                r = await self.process_target(target, db)
            except Exception as exc:
                logger.exception("target '%s' failed: %s", target.label, exc)
                continue
            s += r.scanned
            n += r.new_ads
            a += len(r.alerts)
        return s, n, a

    async def scan_query(self, query: str, db: Database) -> ScanResult:
        """One-off scan for an arbitrary query (Telegram /search)."""
        target = Target.adhoc(query)
        return await self.process_target(target, db)


# --------------------------------------------------------------------------- #
# Telegram command handling
# --------------------------------------------------------------------------- #
def _render_adhoc_reply(result: ScanResult) -> str:
    t = result.target
    lines = [f"\U0001F50D <b>Scan '{t.label}'</b>"]
    lines.append(
        f"scanned {result.scanned} relevant \u00b7 {result.new_ads} new \u00b7 "
        f"{len(result.alerts)} alert(s)"
    )
    bench = []
    if result.mpb:
        bench.append(f"MPB {result.mpb:,.0f}\u20ac")
    if result.ebay:
        bench.append(f"eBay {result.ebay:,.0f}\u20ac")
    if result.f64:
        bench.append(f"F64 {result.f64:,.0f}\u20ac")
    if bench:
        lines.append("benchmarks: " + " \u00b7 ".join(bench))
    if not result.alerts and result.cheapest:
        lines.append("\nCheapest matches:")
        for it in result.cheapest:
            lines.append(f"\u2022 {it.price:,.0f}\u20ac \u2014 <a href=\"{it.link}\">{it.title[:60]}</a>")
    return "\n".join(lines)


async def collect_commands(notifier: TelegramNotifier, db: Database) -> list[cmd.Command]:
    """Poll Telegram once, return authorized commands and advance the offset.

    Runs without a browser so empty poll cycles stay cheap (the poller fires
    every few minutes); the browser is only launched if commands are returned.
    """
    if not notifier.enabled:
        logger.warning("telegram disabled; cannot listen for commands")
        return []

    offset = int(db.get_state("tg_offset", "0") or 0)
    updates = await notifier.get_updates(offset=offset, timeout=settings.command_poll_timeout)

    out: list[cmd.Command] = []
    for upd in updates:
        update_id = upd.get("update_id", 0)
        db.set_state("tg_offset", str(update_id + 1))  # advance even on errors

        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = msg.get("text") or ""

        if settings.telegram_chat_id and chat_id != str(settings.telegram_chat_id):
            logger.info("ignoring message from unauthorized chat %s", chat_id)
            continue
        if not text.startswith("/"):
            continue

        command = cmd.parse(text)
        logger.info("queued command: %s arg=%r", command.action, command.arg)
        out.append(command)
    return out


def _needs_browser(commands: list[cmd.Command]) -> bool:
    return any(c.action in ("scan_all", "scan_query") for c in commands)


async def _dispatch(command: cmd.Command, notifier: TelegramNotifier, db: Database, sniper: "Sniper | None" = None) -> None:
    if command.action in ("scan_all", "scan_query") and sniper is None:
        await notifier.send_text("\u26A0\uFE0F internal error: scan requested without a browser")
        return

    if command.action == "help":
        await notifier.send_text(cmd.HELP_TEXT)

    elif command.action == "list":
        labels = list_labels()
        body = "\n".join(f"{i+1}. {l}" for i, l in enumerate(labels)) or "(none)"
        await notifier.send_text(f"\U0001F4CB <b>Tracked targets</b>\n{body}")

    elif command.action == "add":
        changed, msg = add_target(command.arg)
        await notifier.send_text(("\u2705 " if changed else "\u2139\uFE0F ") + msg)

    elif command.action == "remove":
        changed, msg = remove_target(command.arg)
        await notifier.send_text(("\u2705 " if changed else "\u2139\uFE0F ") + msg)

    elif command.action == "clear":
        removed = db.clear_seen(command.arg or None)
        scope = f" matching '{command.arg}'" if command.arg else ""
        await notifier.send_text(
            f"\U0001F9F9 Forgot {removed} seen ad(s){scope}. "
            "The next scan will re-check them from scratch."
        )

    elif command.action == "scan_all":
        n_targets = len(list_labels())
        await notifier.send_text(
            f"\U0001F3AF <b>Scan started</b> \u2014 {n_targets} target(s). "
            "Scraping providers + benchmarks, I'll report back when done\u2026"
        )
        s, n, a = await sniper.scan_all(db)
        await notifier.send_text(
            f"\u2705 <b>Scan finished</b>\n"
            f"\u2022 scanned: {s}\n\u2022 new ads: {n}\n\u2022 alerts: {a}"
        )

    elif command.action == "scan_query":
        if not command.arg:
            await notifier.send_text("usage: /scan <query>")
            return
        await notifier.send_text(
            f"\U0001F50D <b>Scan started</b> for '<b>{command.arg}</b>'\u2026 "
            "this can take up to a minute."
        )
        result = await sniper.scan_query(command.arg, db)
        await notifier.send_text(_render_adhoc_reply(result))

    else:
        await notifier.send_text("Unknown command. Send /help.")


# --------------------------------------------------------------------------- #
# entrypoints
# --------------------------------------------------------------------------- #
async def amain(args: argparse.Namespace) -> int:
    for p in settings.validate():
        logger.warning("config: %s", p)

    if args.dry_run or settings.dry_run:
        ok = await TelegramNotifier().send_text("\u2705 ArbitrageSniper dry-run ping: bot is alive.")
        logger.info("dry-run ping sent=%s", ok)
        return 0

    db = Database()
    run_id = db.start_run()
    scanned = new_ads = alerts = 0
    note = args.query or ("listen" if args.listen else "scan")
    notifier = TelegramNotifier()
    try:
        if args.listen:
            # Poll first WITHOUT a browser so empty cycles are cheap.
            pending = await collect_commands(notifier, db)
            note = f"listen ({len(pending)} cmds)"
            if not pending:
                logger.info("listen: no commands")
            elif _needs_browser(pending):
                async with BrowserManager() as browser:
                    sniper = Sniper(browser)
                    for command in pending:
                        await _safe_dispatch(command, notifier, db, sniper)
            else:
                for command in pending:
                    await _safe_dispatch(command, notifier, db, None)
        elif args.query:
            async with BrowserManager() as browser:
                sniper = Sniper(browser)
                result = await sniper.scan_query(args.query, db)
                scanned, new_ads, alerts = result.scanned, result.new_ads, len(result.alerts)
                await notifier.send_text(_render_adhoc_reply(result))
        else:
            async with BrowserManager() as browser:
                sniper = Sniper(browser)
                scanned, new_ads, alerts = await sniper.scan_all(db)
                if args.summary and not settings.dry_run:
                    await notifier.send_summary(scanned=scanned, new_ads=new_ads, alerts=alerts)
    finally:
        db.finish_run(run_id, scanned=scanned, new_ads=new_ads, alerts=alerts, note=note)
        logger.info("run done | scanned=%d new=%d alerts=%d | %s", scanned, new_ads, alerts, db.stats())
        db.close()
    return 0


async def _safe_dispatch(command: cmd.Command, notifier: TelegramNotifier, db: Database, sniper: "Sniper | None") -> None:
    try:
        await _dispatch(command, notifier, db, sniper)
    except Exception as exc:
        logger.exception("command failed: %s", exc)
        await notifier.send_text(f"\u26A0\uFE0F command error: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="ArbitrageSniper - used-gear arbitrage scanner")
    parser.add_argument("--dry-run", action="store_true", help="send a Telegram ping and exit")
    parser.add_argument("--summary", action="store_true", help="send a run summary to Telegram")
    parser.add_argument("--listen", action="store_true", help="process pending Telegram commands")
    parser.add_argument("--query", metavar="Q", help="run a one-off scan for a single query")
    args = parser.parse_args()
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
