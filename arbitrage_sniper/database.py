"""SQLite de-duplication store.

The DB file (``seen_ads.db``) is committed back to the repository by the
GitHub Action so that state persists across the (stateless) scheduled runs.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from .config import DB_PATH
from .models import Alert, Item

logger = logging.getLogger("arbitrage_sniper.database")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_ads (
    unique_key   TEXT PRIMARY KEY,
    platform     TEXT NOT NULL,
    ad_id        TEXT NOT NULL,
    title        TEXT,
    price        REAL,
    link         TEXT,
    alerted      INTEGER NOT NULL DEFAULT 0,
    safe_gain    REAL,
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_seen_platform ON seen_ads(platform);
CREATE INDEX IF NOT EXISTS idx_seen_alerted ON seen_ads(alerted);

CREATE TABLE IF NOT EXISTS run_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  INTEGER NOT NULL,
    finished_at INTEGER,
    scanned     INTEGER DEFAULT 0,
    new_ads     INTEGER DEFAULT 0,
    alerts      INTEGER DEFAULT 0,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Columns added after the initial release (applied via ALTER TABLE if missing).
_MIGRATIONS = {
    "target_label": "TEXT",
    "currency": "TEXT",
    "condition": "TEXT",
    "image_url": "TEXT",
    "location": "TEXT",
    "in_range": "INTEGER",
    "mpb_price": "REAL",
    "ebay_price": "REAL",
    "f64_price": "REAL",
    "reason": "TEXT",
}


class Database:
    """Thin synchronous wrapper around sqlite3 (fast enough for this workload)."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        existing = {r[1] for r in self.conn.execute("PRAGMA table_info(seen_ads)")}
        for column, coltype in _MIGRATIONS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE seen_ads ADD COLUMN {column} {coltype}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_target ON seen_ads(target_label)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_seen_last ON seen_ads(last_seen)")

    # ------------------------------------------------------------------ #
    # de-duplication
    # ------------------------------------------------------------------ #
    def is_seen(self, item: Item) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen_ads WHERE unique_key = ? LIMIT 1", (item.unique_key,)
        )
        return cur.fetchone() is not None

    def filter_new(self, items: Iterable[Item]) -> list[Item]:
        """Return only the items we have never recorded before."""
        new: list[Item] = []
        for item in items:
            if not self.is_seen(item):
                new.append(item)
        return new

    def record_scan(
        self,
        item: Item,
        *,
        target_label: str | None = None,
        alerted: bool = False,
        in_range: bool | None = None,
        safe_gain: float | None = None,
        mpb_price: float | None = None,
        ebay_price: float | None = None,
        f64_price: float | None = None,
        reason: str | None = None,
    ) -> None:
        """Upsert a scanned (name-matched) listing with full context.

        Stored regardless of whether it triggered an alert, so the dashboard can
        show everything that matched by name — including out-of-range items.
        """
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO seen_ads
                (unique_key, platform, ad_id, title, price, link, alerted, safe_gain,
                 target_label, currency, condition, image_url, location,
                 in_range, mpb_price, ebay_price, f64_price, reason,
                 first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unique_key) DO UPDATE SET
                last_seen    = excluded.last_seen,
                price        = excluded.price,
                alerted      = MAX(seen_ads.alerted, excluded.alerted),
                safe_gain    = COALESCE(excluded.safe_gain, seen_ads.safe_gain),
                target_label = COALESCE(excluded.target_label, seen_ads.target_label),
                currency     = COALESCE(excluded.currency, seen_ads.currency),
                condition    = COALESCE(excluded.condition, seen_ads.condition),
                image_url    = COALESCE(excluded.image_url, seen_ads.image_url),
                location     = COALESCE(excluded.location, seen_ads.location),
                in_range     = COALESCE(excluded.in_range, seen_ads.in_range),
                mpb_price    = COALESCE(excluded.mpb_price, seen_ads.mpb_price),
                ebay_price   = COALESCE(excluded.ebay_price, seen_ads.ebay_price),
                f64_price    = COALESCE(excluded.f64_price, seen_ads.f64_price),
                reason       = COALESCE(excluded.reason, seen_ads.reason)
            """,
            (
                item.unique_key,
                item.platform,
                item.id,
                item.title,
                item.price,
                item.link,
                1 if alerted else 0,
                safe_gain,
                target_label,
                item.currency,
                item.condition,
                item.image_url,
                item.location,
                None if in_range is None else (1 if in_range else 0),
                mpb_price,
                ebay_price,
                f64_price,
                reason,
                now,
                now,
            ),
        )
        self.conn.commit()

    def record_item(self, item: Item, *, alerted: bool = False, safe_gain: float | None = None) -> None:
        # Backwards-compatible thin wrapper.
        self.record_scan(item, alerted=alerted, safe_gain=safe_gain)

    def record_alert(self, alert: Alert) -> None:
        self.record_scan(
            alert.item,
            target_label=alert.target_label,
            alerted=True,
            in_range=alert.in_range,
            safe_gain=alert.safe_gain,
            mpb_price=alert.mpb_price,
            ebay_price=alert.ebay_price,
            f64_price=alert.f64_price,
            reason=alert.reason,
        )

    def clear_seen(self, like: str | None = None) -> int:
        """Forget previously-seen ads so the next scan re-notifies them.

        With ``like`` set, only ads whose title/platform/link matches the
        (case-insensitive) substring are forgotten; otherwise the whole
        de-dup table is wiped. Returns the number of rows removed.
        """
        if like:
            pattern = f"%{like.lower()}%"
            cur = self.conn.execute(
                "DELETE FROM seen_ads WHERE lower(title) LIKE ? "
                "OR lower(platform) LIKE ? OR lower(link) LIKE ?",
                (pattern, pattern, pattern),
            )
        else:
            cur = self.conn.execute("DELETE FROM seen_ads")
        self.conn.commit()
        return cur.rowcount if cur.rowcount is not None else 0

    # ------------------------------------------------------------------ #
    # run bookkeeping
    # ------------------------------------------------------------------ #
    def start_run(self) -> int:
        cur = self.conn.execute(
            "INSERT INTO run_log (started_at) VALUES (?)", (int(time.time()),)
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, *, scanned: int, new_ads: int, alerts: int, note: str = "") -> None:
        self.conn.execute(
            """
            UPDATE run_log
               SET finished_at = ?, scanned = ?, new_ads = ?, alerts = ?, note = ?
             WHERE id = ?
            """,
            (int(time.time()), scanned, new_ads, alerts, note, run_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ #
    # generic key/value state (e.g. Telegram getUpdates offset)
    # ------------------------------------------------------------------ #
    def get_state(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM bot_state WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else default

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO bot_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self.conn.commit()

    def stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM seen_ads").fetchone()[0]
        alerted = self.conn.execute("SELECT COUNT(*) FROM seen_ads WHERE alerted = 1").fetchone()[0]
        in_range = self.conn.execute(
            "SELECT COUNT(*) FROM seen_ads WHERE in_range = 1"
        ).fetchone()[0]
        return {"total_seen": total, "total_alerted": alerted, "total_in_range": in_range}

    # ------------------------------------------------------------------ #
    # read API for the web dashboard
    # ------------------------------------------------------------------ #
    def _build_filters(
        self,
        *,
        target: str | None,
        in_range: bool | None,
        alerted: bool | None,
        platform: str | None,
        q: str | None,
    ) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if target:
            clauses.append("target_label = ?")
            params.append(target)
        if in_range is not None:
            clauses.append("in_range = ?")
            params.append(1 if in_range else 0)
        if alerted is not None:
            clauses.append("alerted = ?")
            params.append(1 if alerted else 0)
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        if q:
            clauses.append("lower(title) LIKE ?")
            params.append(f"%{q.lower()}%")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    _SORT_COLUMNS = {
        "last_seen": "last_seen",
        "first_seen": "first_seen",
        "price": "price",
        "safe_gain": "safe_gain",
    }

    def list_items(
        self,
        *,
        target: str | None = None,
        in_range: bool | None = None,
        alerted: bool | None = None,
        platform: str | None = None,
        q: str | None = None,
        sort: str = "last_seen",
        descending: bool = True,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        where, params = self._build_filters(
            target=target, in_range=in_range, alerted=alerted, platform=platform, q=q
        )
        col = self._SORT_COLUMNS.get(sort, "last_seen")
        direction = "DESC" if descending else "ASC"
        sql = (
            "SELECT unique_key, platform, ad_id, title, price, link, alerted, safe_gain, "
            "target_label, currency, condition, image_url, location, in_range, "
            "mpb_price, ebay_price, f64_price, reason, first_seen, last_seen "
            f"FROM seen_ads{where} ORDER BY {col} {direction} LIMIT ? OFFSET ?"
        )
        rows = self.conn.execute(sql, (*params, int(limit), int(offset))).fetchall()
        return [dict(r) for r in rows]

    def count_items(
        self,
        *,
        target: str | None = None,
        in_range: bool | None = None,
        alerted: bool | None = None,
        platform: str | None = None,
        q: str | None = None,
    ) -> int:
        where, params = self._build_filters(
            target=target, in_range=in_range, alerted=alerted, platform=platform, q=q
        )
        return self.conn.execute(
            f"SELECT COUNT(*) FROM seen_ads{where}", params
        ).fetchone()[0]

    def distinct_targets(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT target_label FROM seen_ads "
            "WHERE target_label IS NOT NULL AND target_label != '' ORDER BY target_label"
        ).fetchall()
        return [r[0] for r in rows]

    def distinct_platforms(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT platform FROM seen_ads ORDER BY platform"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
