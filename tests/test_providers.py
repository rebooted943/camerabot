"""Tests for provider selection (enabled set + name resolution)."""

import json

from arbitrage_sniper.providers import ALL_PROVIDERS, provider_names, resolve_providers
from arbitrage_sniper.targets import get_enabled_providers, set_enabled_providers


def test_provider_names_nonempty():
    names = provider_names()
    assert "subito" in names or "olx" in names
    assert len(names) == len(ALL_PROVIDERS)


def test_resolve_all_when_empty():
    assert resolve_providers(None) == list(ALL_PROVIDERS)
    assert resolve_providers([]) == list(ALL_PROVIDERS)


def test_resolve_subset_and_unknown():
    picked = resolve_providers(["olx", "does-not-exist"])
    assert [p.name for p in picked] == ["olx"]


def test_resolve_is_case_insensitive():
    picked = resolve_providers(["OLX"])
    assert [p.name for p in picked] == ["olx"]


def _thr(tmp_path):
    p = tmp_path / "thresholds.json"
    p.write_text(json.dumps({"targets": []}), encoding="utf-8")
    return p


def test_enabled_providers_roundtrip(tmp_path):
    p = _thr(tmp_path)
    assert get_enabled_providers(p) is None  # default: all
    set_enabled_providers(["olx", "vinted"], path=p)
    assert get_enabled_providers(p) == ["olx", "vinted"]


def test_enabled_providers_reset(tmp_path):
    p = _thr(tmp_path)
    set_enabled_providers(["olx"], path=p)
    set_enabled_providers(None, path=p)  # reset -> all
    assert get_enabled_providers(p) is None
