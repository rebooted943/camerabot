"""Tests for hosted-deployment bits: data seeding + API token auth."""

import types

from fastapi.testclient import TestClient

from arbitrage_sniper import config
from arbitrage_sniper.web import app as webmod


# --- data seeding ---------------------------------------------------------- #
def test_ensure_data_files_seeds_from_bundled(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    thr = data_dir / "thresholds.json"
    bundled = tmp_path / "bundled.json"
    bundled.write_text('{"targets": [{"label": "X", "queries": ["x"]}]}', encoding="utf-8")

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "THRESHOLDS_PATH", thr)
    monkeypatch.setattr(config, "_BUNDLED_THRESHOLDS", bundled)

    config.ensure_data_files()
    assert thr.exists()
    assert "X" in thr.read_text(encoding="utf-8")


def test_ensure_data_files_template_when_no_bundle(tmp_path, monkeypatch):
    data_dir = tmp_path / "d"
    thr = data_dir / "thresholds.json"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "THRESHOLDS_PATH", thr)
    monkeypatch.setattr(config, "_BUNDLED_THRESHOLDS", tmp_path / "missing.json")

    config.ensure_data_files()
    assert thr.exists()
    assert "targets" in thr.read_text(encoding="utf-8")


# --- auth middleware ------------------------------------------------------- #
def test_health_is_public_and_open_by_default():
    with TestClient(webmod.app) as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True


def test_auth_enforced_when_token_set(monkeypatch):
    fake = types.SimpleNamespace(
        auth_required=True, dashboard_token="secret",
        scan_interval_min=0, facebook_cookies_path="",
    )
    monkeypatch.setattr(webmod, "settings", fake)
    with TestClient(webmod.app) as c:
        # health stays public
        assert c.get("/api/health").status_code == 200
        # guarded endpoint blocked without token
        assert c.get("/api/providers").status_code == 401
        # allowed with the right token (header)
        ok = c.get("/api/providers", headers={"X-Auth-Token": "secret"})
        assert ok.status_code == 200
        # and via Authorization: Bearer
        ok2 = c.get("/api/providers", headers={"Authorization": "Bearer secret"})
        assert ok2.status_code == 200
        # wrong token rejected
        assert c.get("/api/providers", headers={"X-Auth-Token": "nope"}).status_code == 401
