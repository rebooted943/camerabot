"""Minimal currency normalisation.

Providers report prices in mixed currencies (OLX/Publi24/Vinted.ro -> RON,
Wallapop/eBay.de/MPB -> EUR). The arbitrage engine compares everything in EUR,
so all prices are converted to EUR up front.

Rates are static and configurable via env (FX_RON_EUR, FX_USD_EUR, FX_GBP_EUR)
because a scheduled job should not depend on a live FX API for correctness;
operators can refresh them periodically. Defaults are conservative approximations.
"""

from __future__ import annotations

import os

# 1 unit of CURRENCY == N EUR
_DEFAULT_RATES = {
    "EUR": 1.0,
    "RON": 0.20,   # ~1 RON ≈ 0.20 EUR
    "USD": 0.92,
    "GBP": 1.17,
}


def _rate(currency: str) -> float:
    currency = (currency or "EUR").upper()
    env_key = f"FX_{currency}_EUR"
    raw = os.getenv(env_key)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_RATES.get(currency, 1.0)


def to_eur(amount: float, currency: str) -> float:
    """Convert ``amount`` in ``currency`` to EUR."""
    if amount is None:
        return 0.0
    return round(float(amount) * _rate(currency), 2)
