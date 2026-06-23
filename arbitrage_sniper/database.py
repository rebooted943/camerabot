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


class Database:
    """Thin synchronous wrapper around sqlite3 (fast enough for this workload)."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

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

    def record_item(self, item: Item, *, alerted: bool = False, safe_gain: float | None = None) -> None:
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO seen_ads
                (unique_key, platform, ad_id, title, price, link, alerted, safe_gain, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unique_key) DO UPDATE SET
                last_seen = excluded.last_seen,
                price     = excluded.price,
                alerted   = MAX(seen_ads.alerted, excluded.alerted),
                safe_gain = COALESCE(excluded.safe_gain, seen_ads.safe_gain)
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
                now,
                now,
            ),
        )
        self.conn.commit()

    def record_alert(self, alert: Alert) -> None:
        self.record_item(alert.item, alerted=True, safe_gain=alert.safe_gain)

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
        return {"total_seen": total, "total_alerted": alerted}

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
