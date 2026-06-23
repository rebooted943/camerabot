"""Centralised runtime configuration (read from environment / .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "seen_ads.db"
THRESHOLDS_PATH = PROJECT_ROOT / "thresholds.json"


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """Immutable view of the effective configuration for a run."""

    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    ebay_app_token: str = field(default_factory=lambda: os.getenv("EBAY_APP_TOKEN", ""))

    headless: bool = field(default_factory=lambda: _bool("HEADLESS", True))
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))

    # Trigger: buy_price <= mpb_price * mpb_margin  (default 0.90 => 10% cushion)
    mpb_margin: float = field(default_factory=lambda: _float("MPB_MARGIN", 0.90))

    min_delay: float = field(default_factory=lambda: _float("MIN_DELAY", 2.0))
    max_delay: float = field(default_factory=lambda: _float("MAX_DELAY", 6.0))
    max_items_per_provider: int = field(
        default_factory=lambda: _int("MAX_ITEMS_PER_PROVIDER", 40)
    )

    nav_timeout_ms: int = field(default_factory=lambda: _int("NAV_TIMEOUT_MS", 30000))

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems (empty == OK)."""
        problems: list[str] = []
        if not self.telegram_token:
            problems.append("TELEGRAM_TOKEN is not set (notifications disabled).")
        if not self.telegram_chat_id:
            problems.append("TELEGRAM_CHAT_ID is not set (notifications disabled).")
        if self.min_delay < 0 or self.max_delay < self.min_delay:
            problems.append("Invalid MIN_DELAY/MAX_DELAY range.")
        if not (0 < self.mpb_margin <= 1):
            problems.append("MPB_MARGIN must be in (0, 1].")
        return problems


settings = Settings()
