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

# State locations are env-overridable so the same code runs from the repo
# checkout (GitHub Actions) or from a persistent volume on a hosted deployment.
#   DATA_DIR        -> base dir for both files (default: repo root)
#   DB_PATH         -> explicit override for the SQLite file
#   THRESHOLDS_PATH -> explicit override for the config file
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT)))
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "seen_ads.db")))
THRESHOLDS_PATH = Path(os.getenv("THRESHOLDS_PATH", str(DATA_DIR / "thresholds.json")))

# The version bundled in the repo, used to seed a fresh volume on first boot.
_BUNDLED_THRESHOLDS = PROJECT_ROOT / "thresholds.json"


def ensure_data_files() -> None:
    """Make sure DATA_DIR exists and thresholds.json is present.

    On a hosted deployment DATA_DIR is an empty persistent volume, so seed it
    from the repo's committed thresholds.json (or a minimal template).
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if THRESHOLDS_PATH.exists():
        return
    try:
        if _BUNDLED_THRESHOLDS.exists() and _BUNDLED_THRESHOLDS != THRESHOLDS_PATH:
            THRESHOLDS_PATH.write_text(
                _BUNDLED_THRESHOLDS.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            THRESHOLDS_PATH.write_text('{\n  "targets": []\n}\n', encoding="utf-8")
    except OSError:
        pass


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
    # Playwright cookies JSON for Facebook Marketplace (optional but recommended).
    facebook_cookies_path: str = field(default_factory=lambda: os.getenv("FACEBOOK_COOKIES_PATH", ""))

    headless: bool = field(default_factory=lambda: _bool("HEADLESS", True))
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))

    # Trigger: buy_price <= mpb_price * mpb_margin  (default 0.90 => 10% cushion)
    mpb_margin: float = field(default_factory=lambda: _float("MPB_MARGIN", 0.90))
    # Sanity guard: reject "too good to be true" deals (default 500%). A gain
    # above this almost always means a scam, a mis-parsed price or a part-out.
    max_gain_pct: float = field(default_factory=lambda: _float("MAX_GAIN_PCT", 500.0))

    min_delay: float = field(default_factory=lambda: _float("MIN_DELAY", 2.0))
    max_delay: float = field(default_factory=lambda: _float("MAX_DELAY", 6.0))
    max_items_per_provider: int = field(
        default_factory=lambda: _int("MAX_ITEMS_PER_PROVIDER", 40)
    )

    # Vinted: scan all EU storefronts by default (west + east). Override with
    # VINTED_REGIONS=west|east|west,east  or  VINTED_MARKETS=it,ro,fr,pl
    vinted_regions: str = field(default_factory=lambda: os.getenv("VINTED_REGIONS", "west,east"))
    vinted_markets: str = field(default_factory=lambda: os.getenv("VINTED_MARKETS", ""))
    # Items fetched per Vinted storefront before merging (lower = faster runs).
    vinted_per_store: int = field(default_factory=lambda: _int("VINTED_PER_STORE", 12))

    nav_timeout_ms: int = field(default_factory=lambda: _int("NAV_TIMEOUT_MS", 30000))

    # Telegram command listener (poll getUpdates once per --listen run).
    command_poll_timeout: int = field(default_factory=lambda: _int("COMMAND_POLL_TIMEOUT", 0))

    # --- hosted dashboard (web) options ---
    # Shared token protecting the /api/* endpoints. Empty => API is open (local).
    dashboard_token: str = field(default_factory=lambda: os.getenv("DASHBOARD_TOKEN", ""))
    # Built-in periodic scan interval (minutes) for the always-on server.
    # 0 disables it (default): rely on the "Scan now" button or GitHub Actions.
    scan_interval_min: int = field(default_factory=lambda: _int("SCAN_INTERVAL_MIN", 0))

    @property
    def auth_required(self) -> bool:
        return bool(self.dashboard_token)

    @property
    def is_ci(self) -> bool:
        return _bool("CI", False)

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
