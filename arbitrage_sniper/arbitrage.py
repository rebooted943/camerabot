"""Core arbitrage logic: the selective filter and spread calculator.

This module is intentionally pure (no I/O) so it is trivial to unit-test:
given an Item plus its benchmarks, decide whether it triggers and compute the
two gain metrics.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import settings
from .models import Alert, Benchmark, Item, price_in_range

logger = logging.getLogger("arbitrage_sniper.arbitrage")


def evaluate(
    item: Item,
    *,
    target_label: str,
    mpb: Optional[Benchmark] = None,
    ebay: Optional[Benchmark] = None,
    f64: Optional[Benchmark] = None,
    margin: Optional[float] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
) -> Optional[Alert]:
    """Decide whether a listing should trigger an alert.

    Two modes, chosen automatically:

    * **Price-range mode** (a ``price_max``/``price_min`` is configured on the
      target): alert when ``price_min <= buy_price <= price_max``. MPB / eBay /
      F64 are still attached to the alert for context when available. This is
      the intuitive "notify me when an A7 III shows up between 400 and 700 EUR".

    * **MPB mode** (no explicit range): the original risk-zero rule
      ``buy_price <= mpb_price * margin`` with the ``MAX_GAIN_PCT`` sanity guard.

    Returns an :class:`Alert` if it fires, else ``None``. (Relevance/name
    matching happens upstream; this function only prices the decision.)
    """
    margin = settings.mpb_margin if margin is None else margin

    if item.price <= 0:
        logger.debug("skip %s: non-positive price", item.unique_key)
        return None

    mpb_value = float(mpb.value) if (mpb and mpb.available) else None
    ebay_value = ebay.value if (ebay and ebay.available) else None
    f64_value = f64.value if (f64 and f64.available) else None
    in_range = price_in_range(item.price, price_min, price_max)
    has_range = price_min is not None or price_max is not None

    def build(reason: str) -> Alert:
        return Alert(
            item=item,
            target_label=target_label,
            mpb_price=mpb_value,
            ebay_price=ebay_value,
            f64_price=f64_value,
            margin_used=margin,
            in_range=in_range,
            reason=reason,
        )

    if has_range:
        # Price-window mode: the user-defined range is the alert gate.
        if not in_range:
            return None
        logger.info(
            "TRIGGER(range) %s | buy=%.2f in [%s, %s]",
            item.unique_key, item.price, price_min, price_max,
        )
        return build("range")

    # MPB mode (no explicit range configured).
    if mpb_value is None:
        logger.debug("skip %s: no MPB benchmark and no price range", item.unique_key)
        return None

    trigger_price = mpb_value * margin
    if item.price > trigger_price:
        logger.debug(
            "skip %s: price %.2f > trigger %.2f (mpb %.2f x %.2f)",
            item.unique_key, item.price, trigger_price, mpb_value, margin,
        )
        return None

    alert = build("mpb")

    # Sanity guard: an implausibly large gain is almost always a scam, a
    # mis-parsed price, or a "for parts" listing. Drop it instead of alerting.
    if alert.safe_gain_pct is not None and alert.safe_gain_pct > settings.max_gain_pct:
        logger.warning(
            "skip %s: suspicious gain %.0f%% (> %.0f%% cap) buy=%.2f mpb=%.2f",
            item.unique_key, alert.safe_gain_pct, settings.max_gain_pct,
            item.price, mpb_value,
        )
        return None

    logger.info(
        "TRIGGER(mpb) %s | buy=%.2f mpb=%.2f safe_gain=%.2f potential=%s",
        item.unique_key, item.price, mpb_value, alert.safe_gain, alert.potential_gain,
    )
    return alert


def best_retail_benchmark(
    ebay: Optional[Benchmark], f64: Optional[Benchmark]
) -> Optional[Benchmark]:
    """Pick the most informative retail benchmark (prefer eBay-sold averages)."""
    candidates = [b for b in (ebay, f64) if b and b.available]
    if not candidates:
        return None
    # Prefer the one with the larger sample size, then the higher value.
    return max(candidates, key=lambda b: (b.sample_size, b.value or 0))
