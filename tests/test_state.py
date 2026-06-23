"""Tests for de-dup reset (/clear) and per-target channel routing."""

from arbitrage_sniper.commands import parse
from arbitrage_sniper.database import Database
from arbitrage_sniper.models import Item
from arbitrage_sniper.targets import Target


def _item(platform, ad_id, title):
    return Item(id=ad_id, title=title, price=100.0, link=f"https://{platform}/{ad_id}", platform=platform)


def test_clear_all(tmp_path):
    db = Database(tmp_path / "t.db")
    db.record_item(_item("olx", "1", "Sony A7 III"))
    db.record_item(_item("vinted", "2", "Canon EOS R6"))
    assert db.stats()["total_seen"] == 2
    removed = db.clear_seen()
    assert removed == 2
    assert db.stats()["total_seen"] == 0
    db.close()


def test_clear_by_query(tmp_path):
    db = Database(tmp_path / "t.db")
    db.record_item(_item("olx", "1", "Sony A7 III body"))
    db.record_item(_item("vinted", "2", "Canon EOS R6"))
    removed = db.clear_seen("sony")
    assert removed == 1
    assert db.stats()["total_seen"] == 1
    db.close()


def test_clear_command_parsing():
    assert parse("/clear").action == "clear"
    assert parse("/reset").action == "clear"
    c = parse("/clear sony a7")
    assert c.action == "clear" and c.arg == "sony a7"


def test_target_named_channel_routing():
    channels = {"sony": {"chat_id": "-100999", "topic_id": 12}}
    t = Target.from_dict({"label": "Sony A7 III", "queries": ["a7 iii"], "channel": "sony"}, channels)
    assert t.chat_id == "-100999"
    assert t.topic_id == 12


def test_target_direct_routing_overrides():
    t = Target.from_dict(
        {"label": "X", "queries": ["x"], "chat_id": "-100777", "topic_id": 5}, {}
    )
    assert t.chat_id == "-100777" and t.topic_id == 5


def test_target_default_routing_none():
    t = Target.from_dict({"label": "X", "queries": ["x"]}, {})
    assert t.chat_id is None and t.topic_id is None


def test_target_roundtrip_channel_in_to_dict():
    t = Target.from_dict({"label": "X", "queries": ["x"], "channel": "sony"}, {})
    assert t.to_dict().get("channel") == "sony"
