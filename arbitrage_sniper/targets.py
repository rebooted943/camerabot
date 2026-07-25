"""Target model + thresholds.json management (load / save / add / remove).

Editing here is what the Telegram ``/add`` and ``/remove`` commands drive; the
GitHub Action commits the modified ``thresholds.json`` back to the repo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import THRESHOLDS_PATH
from .matching import auto_include_terms, normalize


def _num(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Target:
    label: str
    queries: list[str]
    mpb_id: str | None = None
    mpb_floor: float | None = None
    ebay_query: str | None = None
    f64_query: str | None = None
    include_terms: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    # Optional price window (EUR). When set, it becomes the alert gate:
    # notify when price_min <= buy_price <= price_max. Either bound may be None.
    price_min: float | None = None
    price_max: float | None = None
    # Optional Telegram routing: send this target's alerts to a specific
    # channel/chat and (optionally) a forum topic thread.
    channel: str | None = None
    chat_id: str | None = None
    topic_id: int | None = None

    @property
    def primary_query(self) -> str:
        return self.queries[0] if self.queries else self.label

    @property
    def effective_include(self) -> list[str]:
        """Include terms to enforce; auto-derived from the query if unset."""
        return self.include_terms or auto_include_terms(self.primary_query)

    @classmethod
    def from_dict(cls, d: dict, channels: dict | None = None) -> "Target":
        match = d.get("match") or {}
        channels = channels or {}

        # Resolve routing: a named channel can be referenced via "channel";
        # explicit "chat_id"/"topic_id" on the target override the named one.
        channel = d.get("channel")
        route = dict(channels.get(channel, {})) if channel else {}
        chat_id = d.get("chat_id", route.get("chat_id"))
        topic_id = d.get("topic_id", route.get("topic_id"))

        price = d.get("price") or {}
        return cls(
            label=d["label"],
            queries=d.get("queries") or [d["label"]],
            mpb_id=d.get("mpb_id"),
            mpb_floor=d.get("mpb_floor"),
            ebay_query=d.get("ebay_query"),
            f64_query=d.get("f64_query"),
            include_terms=list(match.get("include") or []),
            exclude_terms=list(match.get("exclude") or []),
            price_min=_num(d.get("price_min", price.get("min"))),
            price_max=_num(d.get("price_max", price.get("max"))),
            channel=channel,
            chat_id=str(chat_id) if chat_id is not None else None,
            topic_id=int(topic_id) if topic_id is not None else None,
        )

    @classmethod
    def adhoc(
        cls,
        query: str,
        price_min: float | None = None,
        price_max: float | None = None,
    ) -> "Target":
        """Build a transient target for a one-off Telegram /search."""
        return cls(
            label=query,
            queries=[query],
            mpb_id=None,
            mpb_floor=None,
            ebay_query=query,
            f64_query=query,
            include_terms=auto_include_terms(query),
            exclude_terms=[],
            price_min=price_min,
            price_max=price_max,
        )

    def to_dict(self) -> dict:
        d: dict = {"label": self.label, "queries": self.queries}
        if self.mpb_id:
            d["mpb_id"] = self.mpb_id
        if self.mpb_floor is not None:
            d["mpb_floor"] = self.mpb_floor
        if self.ebay_query:
            d["ebay_query"] = self.ebay_query
        if self.f64_query:
            d["f64_query"] = self.f64_query
        if self.include_terms or self.exclude_terms:
            d["match"] = {}
            if self.include_terms:
                d["match"]["include"] = self.include_terms
            if self.exclude_terms:
                d["match"]["exclude"] = self.exclude_terms
        if self.price_min is not None:
            d["price_min"] = self.price_min
        if self.price_max is not None:
            d["price_max"] = self.price_max
        if self.channel:
            d["channel"] = self.channel
        if self.chat_id and not self.channel:
            d["chat_id"] = self.chat_id
        if self.topic_id is not None and not self.channel:
            d["topic_id"] = self.topic_id
        return d


def _load_raw(path: Path | str = THRESHOLDS_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save_raw(data: dict, path: Path | str = THRESHOLDS_PATH) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def load_targets(path: Path | str = THRESHOLDS_PATH) -> list[Target]:
    data = _load_raw(path)
    channels = data.get("channels") or {}
    return [Target.from_dict(t, channels) for t in data.get("targets", [])]


def list_labels(path: Path | str = THRESHOLDS_PATH) -> list[str]:
    return [t.label for t in load_targets(path)]


_RANGE_RE = re.compile(
    r"""(?:^|\s)
        (?:
            (?P<lo>\d+(?:[.,]\d+)?)\s*[-\u2013to]+\s*(?P<hi>\d+(?:[.,]\d+)?)  # 400-700
          | <\s*(?P<lt>\d+(?:[.,]\d+)?)                                        # <700
          | >\s*(?P<gt>\d+(?:[.,]\d+)?)                                        # >400
        )\s*(?:eur|€|ron|lei)?\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_query_and_range(text: str) -> tuple[str, float | None, float | None]:
    """Split a free-text add argument into (query, price_min, price_max).

    Accepts a trailing price window: "Sony A7 III 400-700", "Canon R6 <900",
    "Sigma 24-70 >300". Returns the cleaned query plus optional bounds.
    """
    text = (text or "").strip()
    m = _RANGE_RE.search(text)
    if not m:
        return text, None, None
    lo = hi = None
    if m.group("lo") is not None:
        lo = _num(m.group("lo").replace(",", "."))
        hi = _num(m.group("hi").replace(",", "."))
    elif m.group("lt") is not None:
        hi = _num(m.group("lt").replace(",", "."))
    elif m.group("gt") is not None:
        lo = _num(m.group("gt").replace(",", "."))
    query = text[: m.start()].strip()
    return (query or text), lo, hi


def add_target(
    query: str,
    price_min: float | None = None,
    price_max: float | None = None,
    path: Path | str = THRESHOLDS_PATH,
) -> tuple[bool, str]:
    """Add a target from a free-text query (optionally with a price window).

    If ``price_min``/``price_max`` are not given, a trailing range in the query
    (e.g. "Sony A7 III 400-700") is parsed automatically.
    """
    query = (query or "").strip()
    if price_min is None and price_max is None:
        query, price_min, price_max = parse_query_and_range(query)
    if not query:
        return False, "empty query"

    data = _load_raw(path)
    targets = data.setdefault("targets", [])
    norm_q = normalize(query)
    for t in targets:
        if normalize(t.get("label", "")) == norm_q:
            return False, f"'{query}' already tracked"

    new = Target.adhoc(query, price_min=_num(price_min), price_max=_num(price_max))
    targets.append(new.to_dict())
    _save_raw(data, path)

    rng = _fmt_range(new.price_min, new.price_max)
    return True, f"added '{query}'{rng} (tracking {len(targets)} targets)"


def update_target(
    identifier: str,
    updates: dict,
    path: Path | str = THRESHOLDS_PATH,
) -> tuple[bool, str]:
    """Patch a target (matched by index or label). Supported keys: price_min,
    price_max, mpb_id, mpb_floor, channel, chat_id, topic_id, queries."""
    data = _load_raw(path)
    targets = data.get("targets", [])
    idx = _find_index(targets, identifier)
    if idx is None:
        return False, f"no target matching '{identifier}'"

    t = targets[idx]
    for key in ("mpb_id", "mpb_floor", "channel", "chat_id", "topic_id", "queries"):
        if key in updates:
            value = updates[key]
            if value in (None, "", []):
                t.pop(key, None)
            else:
                t[key] = value
    if "price_min" in updates:
        _set_or_pop(t, "price_min", _num(updates["price_min"]))
    if "price_max" in updates:
        _set_or_pop(t, "price_max", _num(updates["price_max"]))

    _save_raw(data, path)
    return True, f"updated '{t.get('label')}'"


def remove_target(token: str, path: Path | str = THRESHOLDS_PATH) -> tuple[bool, str]:
    """Remove a target by 1-based index or by (case-insensitive) label match."""
    data = _load_raw(path)
    targets = data.get("targets", [])
    if not targets:
        return False, "no targets to remove"
    idx = _find_index(targets, token)
    if idx is None:
        return False, f"no target matching '{token}'"
    removed = targets.pop(idx)
    _save_raw(data, path)
    return True, f"removed '{removed.get('label')}'"


def _find_index(targets: list[dict], identifier: str) -> int | None:
    identifier = str(identifier).strip()
    if identifier.isdigit():
        idx = int(identifier) - 1
        return idx if 0 <= idx < len(targets) else None
    norm = normalize(identifier)
    # exact label match first, then substring.
    for i, t in enumerate(targets):
        if normalize(t.get("label", "")) == norm:
            return i
    for i, t in enumerate(targets):
        if norm and norm in normalize(t.get("label", "")):
            return i
    return None


def _set_or_pop(d: dict, key: str, value) -> None:
    if value is None:
        d.pop(key, None)
    else:
        d[key] = value


def _fmt_range(lo: float | None, hi: float | None) -> str:
    if lo is None and hi is None:
        return ""
    if lo is not None and hi is not None:
        return f" [{lo:g}-{hi:g}\u20ac]"
    if hi is not None:
        return f" [\u2264{hi:g}\u20ac]"
    return f" [\u2265{lo:g}\u20ac]"


def range_label(lo: float | None, hi: float | None) -> str:
    """Public helper for formatting a price range (used by /list, UI)."""
    return _fmt_range(lo, hi).strip()
