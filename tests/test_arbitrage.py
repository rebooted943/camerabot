"""Unit tests for the pure arbitrage logic and helpers (no network needed)."""

from arbitrage_sniper import arbitrage
from arbitrage_sniper.currency import to_eur
from arbitrage_sniper.models import Benchmark, Condition, Item, parse_price


def make_item(price: float, **kw) -> Item:
    base = dict(
        id="x1",
        title="Sony A7 III body",
        price=price,
        link="https://olx.ro/x1",
        platform="olx",
    )
    base.update(kw)
    return Item(**base)


def test_trigger_fires_below_margin():
    item = make_item(600.0, currency="EUR")
    mpb = Benchmark(source="mpb", value=720.0)
    alert = arbitrage.evaluate(item, target_label="A7III", mpb=mpb, margin=0.90)
    assert alert is not None
    # trigger price = 720 * 0.9 = 648; 600 <= 648 -> fires
    assert alert.safe_gain == 120.0


def test_trigger_does_not_fire_above_margin():
    item = make_item(700.0, currency="EUR")
    mpb = Benchmark(source="mpb", value=720.0)
    # trigger price = 648; 700 > 648 -> no alert
    assert arbitrage.evaluate(item, target_label="A7III", mpb=mpb, margin=0.90) is None


def test_no_mpb_benchmark_means_no_alert():
    item = make_item(100.0, currency="EUR")
    mpb = Benchmark(source="mpb", value=None)
    assert arbitrage.evaluate(item, target_label="A7III", mpb=mpb) is None


def test_potential_gain_uses_ebay():
    item = make_item(600.0, currency="EUR")
    mpb = Benchmark(source="mpb", value=720.0)
    ebay = Benchmark(source="ebay", value=900.0, sample_size=12)
    alert = arbitrage.evaluate(item, target_label="A7III", mpb=mpb, ebay=ebay, margin=0.90)
    assert alert.potential_gain == 300.0
    assert alert.safe_gain_pct == 20.0


def test_red_flags_detected():
    item = make_item(
        600.0,
        currency="EUR",
        title="Sony A7 III body fungus on lens",
        seller_is_new=True,
    )
    flags = item.red_flags()
    assert any("fungus" in f for f in flags)
    assert "seller:newly-registered" in flags


def test_currency_normalisation_changes_outcome():
    # 3200 RON ≈ 640 EUR at default 0.20 rate -> below 648 trigger.
    eur = to_eur(3200, "RON")
    assert 600 < eur < 700
    item = make_item(eur, currency="EUR")
    mpb = Benchmark(source="mpb", value=720.0)
    assert arbitrage.evaluate(item, target_label="A7III", mpb=mpb, margin=0.90) is not None


def test_parse_price_variants():
    assert parse_price("1.234,56 lei") == 1234.56
    assert parse_price("1,234.56 €") == 1234.56
    assert parse_price("€ 720") == 720.0
    assert parse_price("3200") == 3200.0
    assert parse_price(None) is None


def test_best_retail_prefers_larger_sample():
    ebay = Benchmark(source="ebay", value=900, sample_size=20)
    f64 = Benchmark(source="f64", value=950, sample_size=3)
    best = arbitrage.best_retail_benchmark(ebay, f64)
    assert best.source == "ebay"


def test_condition_enum_value():
    item = make_item(600.0, condition=Condition.GOOD.value)
    assert item.condition == "good"
