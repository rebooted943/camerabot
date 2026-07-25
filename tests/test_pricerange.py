"""Tests for price-window targets, range-mode alerts and the dashboard DB API."""

import json

from arbitrage_sniper import arbitrage
from arbitrage_sniper.database import Database
from arbitrage_sniper.models import Benchmark, Item, price_in_range
from arbitrage_sniper.targets import (
    add_target,
    load_targets,
    parse_query_and_range,
    remove_target,
    update_target,
)


_counter = 0


def _item(price, title="Sony A7 III"):
    global _counter
    _counter += 1
    return Item(id=f"x{_counter}", title=title, price=price, link=f"https://olx/x{_counter}", platform="olx")


# --- price_in_range -------------------------------------------------------- #
def test_price_in_range_bounds():
    assert price_in_range(500, 400, 700)
    assert not price_in_range(800, 400, 700)
    assert not price_in_range(300, 400, 700)
    assert price_in_range(300, None, 700)   # open lower bound
    assert price_in_range(9000, 400, None)  # open upper bound


# --- range-mode evaluation ------------------------------------------------- #
def test_range_mode_alerts_inside_window():
    mpb = Benchmark(source="mpb", value=720.0)
    alert = arbitrage.evaluate(
        _item(500), target_label="A7III", mpb=mpb, price_min=400, price_max=700
    )
    assert alert is not None
    assert alert.reason == "range"
    assert alert.in_range is True
    assert alert.mpb_price == 720.0  # benchmark still attached for context


def test_range_mode_rejects_outside_window():
    alert = arbitrage.evaluate(
        _item(900), target_label="A7III", price_min=400, price_max=700
    )
    assert alert is None


def test_range_mode_without_mpb_still_alerts():
    alert = arbitrage.evaluate(_item(500), target_label="A7III", price_max=700)
    assert alert is not None
    assert alert.mpb_price is None
    assert alert.safe_gain is None


def test_mpb_mode_unchanged_when_no_range():
    mpb = Benchmark(source="mpb", value=720.0)
    assert arbitrage.evaluate(_item(600), target_label="A7III", mpb=mpb, margin=0.90) is not None
    assert arbitrage.evaluate(_item(700), target_label="A7III", mpb=mpb, margin=0.90) is None


# --- query/range parsing --------------------------------------------------- #
def test_parse_query_and_range_dash():
    q, lo, hi = parse_query_and_range("Sony A7 III 400-700")
    assert q == "Sony A7 III" and lo == 400 and hi == 700


def test_parse_query_and_range_lt_gt():
    q, lo, hi = parse_query_and_range("Canon R6 <900")
    assert q == "Canon R6" and lo is None and hi == 900
    q, lo, hi = parse_query_and_range("Sigma 24-70 >300")
    assert lo == 300 and hi is None


def test_parse_query_and_range_none():
    q, lo, hi = parse_query_and_range("Fujifilm X-T50")
    assert q == "Fujifilm X-T50" and lo is None and hi is None


# --- thresholds add/update/remove with ranges ------------------------------ #
def _thr(tmp_path):
    p = tmp_path / "thresholds.json"
    p.write_text(json.dumps({"targets": []}), encoding="utf-8")
    return p


def test_add_target_with_inline_range(tmp_path):
    p = _thr(tmp_path)
    ok, _ = add_target("Sony A7 III 400-700", path=p)
    assert ok
    t = load_targets(p)[0]
    assert t.price_min == 400 and t.price_max == 700


def test_add_target_with_explicit_range(tmp_path):
    p = _thr(tmp_path)
    add_target("Canon R6", 500, 900, path=p)
    t = load_targets(p)[0]
    assert t.price_min == 500 and t.price_max == 900


def test_update_and_remove_target(tmp_path):
    p = _thr(tmp_path)
    add_target("Fujifilm X-T50", path=p)
    ok, _ = update_target("Fujifilm X-T50", {"price_max": 1200}, path=p)
    assert ok
    assert load_targets(p)[0].price_max == 1200
    ok, _ = remove_target("Fujifilm X-T50", path=p)
    assert ok
    assert load_targets(p) == []


# --- dashboard DB read API ------------------------------------------------- #
def test_db_list_and_filter(tmp_path):
    db = Database(tmp_path / "t.db")
    db.record_scan(_item(500, "Sony A7 III body"), target_label="Sony A7 III", in_range=True, alerted=True)
    db.record_scan(_item(1200, "Sony A7 III grip combo"), target_label="Sony A7 III", in_range=False)
    db.record_scan(_item(950, "Canon EOS R6"), target_label="Canon EOS R6", in_range=True)

    assert db.count_items() == 3
    assert db.count_items(in_range=True) == 2
    assert db.count_items(in_range=False) == 1
    assert db.count_items(alerted=True) == 1
    assert db.count_items(target="Canon EOS R6") == 1
    assert db.count_items(q="grip") == 1
    assert set(db.distinct_targets()) == {"Sony A7 III", "Canon EOS R6"}

    cheapest = db.list_items(sort="price", descending=False, limit=1)[0]
    assert cheapest["price"] == 500
    db.close()
