"""Core arbitrage logic: the selective filter and spread calculator.

This module is intentionally pure (no I/O) so it is trivial to unit-test:
given an Item plus its benchmarks, decide whether it triggers and compute the
two gain metrics.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import settings
from .models import Alert, Benchmark, Item

logger = logging.getLogger("arbitrage_sniper.arbitrage")


def evaluate(
    item: Item,
    *,
    target_label: str,
    mpb: Benchmark,
    ebay: Optional[Benchmark] = None,
    f64: Optional[Benchmark] = None,
    margin: Optional[float] = None,
) -> Optional[Alert]:
    """Apply the trigger rule and return an :class:`Alert` if it fires.

    Trigger (risk-zero):
        buy_price <= mpb_price * margin     (margin default 0.90)

    The MPB floor price is the *safety* benchmark: it is what MPB would pay to
    buy the item in Excellent/Good condition, so clearing it with a 10% cushion
    (to cover shipping) means the deal is essentially risk free.
    """
    margin = settings.mpb_margin if margin is None else margin

    if item.price <= 0:
        logger.debug("skip %s: non-positive price", item.unique_key)
        return None

    if not mpb.available:
        logger.debug("skip %s: no MPB benchmark", item.unique_key)
        return None

    trigger_price = mpb.value * margin
    if item.price > trigger_price:
        logger.debug(
            "skip %s: price %.2f > trigger %.2f (mpb %.2f x %.2f)",
            item.unique_key,
            item.price,
            trigger_price,
            mpb.value,
            margin,
        )
        return None

    alert = Alert(
        item=item,
        target_label=target_label,
        mpb_price=float(mpb.value),
        ebay_price=ebay.value if (ebay and ebay.available) else None,
        f64_price=f64.value if (f64 and f64.available) else None,
        margin_used=margin,
    )

    # Sanity guard: an implausibly large gain is almost always a scam, a
    # mis-parsed price, or a "for parts" listing. Drop it instead of alerting.
    if alert.safe_gain_pct > settings.max_gain_pct:
        logger.warning(
            "skip %s: suspicious gain %.0f%% (> %.0f%% cap) buy=%.2f mpb=%.2f",
            item.unique_key,
            alert.safe_gain_pct,
            settings.max_gain_pct,
            item.price,
            alert.mpb_price,
        )
        return None

    logger.info(
        "TRIGGER %s | buy=%.2f mpb=%.2f safe_gain=%.2f potential=%s",
        item.unique_key,
        item.price,
        alert.mpb_price,
        alert.safe_gain,
        alert.potential_gain,
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
