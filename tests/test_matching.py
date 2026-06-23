"""Tests for relevance matching, gain cap and robust benchmark aggregation."""

from arbitrage_sniper import arbitrage
from arbitrage_sniper.benchmarks.base import BaseBenchmark
from arbitrage_sniper.matching import auto_include_terms, is_relevant
from arbitrage_sniper.models import Benchmark, Item


# --- relevance ------------------------------------------------------------- #
A7III_INCLUDE = ["sony", "a7 iii|a7iii|alpha 7 iii"]
A7III_EXCLUDE = ["a7 ii|a7ii|a7 iv|a7iv"]


def test_keeps_exact_model():
    assert is_relevant("Sony A7 III body excellent", A7III_INCLUDE, A7III_EXCLUDE)
    assert is_relevant("Sony A7III mirrorless", A7III_INCLUDE, A7III_EXCLUDE)


def test_drops_accessory_grip():
    # grip is a global default exclude
    assert not is_relevant("Sony A7 III battery grip VG-C3EM", A7III_INCLUDE, A7III_EXCLUDE)


def test_drops_wrong_model_a7ii():
    # "A7 II" lacks the required "iii" token AND hits the exclude list
    assert not is_relevant("Sony A7 II body", A7III_INCLUDE, A7III_EXCLUDE)


def test_iii_token_not_matched_by_ii_exclude():
    # the \bii\b exclude must NOT knock out a genuine "iii" listing
    assert is_relevant("Sony Alpha 7 III", A7III_INCLUDE, A7III_EXCLUDE)


def test_canon_r6_excludes_1300d():
    inc = ["canon", "eos r6|r6"]
    assert is_relevant("Canon EOS R6 body", inc)
    assert not is_relevant("Canon EOS 1300D kit", inc)


def test_xt50_not_matched_by_xt5():
    inc = auto_include_terms("fujifilm x-t50")
    assert is_relevant("Fujifilm X-T50 black", inc)
    assert not is_relevant("Fujifilm X-T5 silver", inc)


def test_auto_include_drops_short_and_stopwords():
    terms = auto_include_terms("Sony A7 III body camera")
    assert "sony" in terms and "iii" in terms and "a7" in terms
    assert "body" not in terms and "camera" not in terms


# --- gain cap -------------------------------------------------------------- #
def _item(price):
    return Item(id="x", title="Sony A7 III", price=price, link="https://o/x", platform="olx")


def test_gain_cap_rejects_too_good_to_be_true():
    item = _item(50.0)  # 50 EUR for a 720 EUR camera -> ~1340% gain
    mpb = Benchmark(source="mpb", value=720.0)
    assert arbitrage.evaluate(item, target_label="A7III", mpb=mpb, margin=0.90) is None


def test_gain_cap_allows_reasonable_deal():
    item = _item(600.0)  # 20% gain
    mpb = Benchmark(source="mpb", value=720.0)
    assert arbitrage.evaluate(item, target_label="A7III", mpb=mpb, margin=0.90) is not None


# --- robust aggregation (F64 25848 bug) ------------------------------------ #
def test_aggregate_drops_out_of_bounds_outlier():
    # the spurious 25848 must be ignored; median of plausible prices returned
    vals = [610.0, 640.0, 25848.0, 600.0, 655.0]
    out = BaseBenchmark._aggregate(vals, lo=10, hi=15000)
    assert 600 <= out <= 660


def test_aggregate_returns_none_when_all_out_of_bounds():
    assert BaseBenchmark._aggregate([25848.0, 99999.0], lo=10, hi=15000) is None
