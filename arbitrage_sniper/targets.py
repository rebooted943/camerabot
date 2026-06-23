"""Target model + thresholds.json management (load / save / add / remove).

Editing here is what the Telegram ``/add`` and ``/remove`` commands drive; the
GitHub Action commits the modified ``thresholds.json`` back to the repo.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import THRESHOLDS_PATH
from .matching import auto_include_terms, normalize


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

        return cls(
            label=d["label"],
            queries=d.get("queries") or [d["label"]],
            mpb_id=d.get("mpb_id"),
            mpb_floor=d.get("mpb_floor"),
            ebay_query=d.get("ebay_query"),
            f64_query=d.get("f64_query"),
            include_terms=list(match.get("include") or []),
            exclude_terms=list(match.get("exclude") or []),
            channel=channel,
            chat_id=str(chat_id) if chat_id is not None else None,
            topic_id=int(topic_id) if topic_id is not None else None,
        )

    @classmethod
    def adhoc(cls, query: str) -> "Target":
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


def add_target(query: str, path: Path | str = THRESHOLDS_PATH) -> tuple[bool, str]:
    """Add a new target derived from a free-text query. Returns (changed, msg)."""
    query = query.strip()
    if not query:
        return False, "empty query"
    data = _load_raw(path)
    targets = data.setdefault("targets", [])
    norm_q = normalize(query)
    for t in targets:
        if normalize(t.get("label", "")) == norm_q:
            return False, f"'{query}' already tracked"
    new = Target.adhoc(query)
    targets.append(new.to_dict())
    _save_raw(data, path)
    return True, f"added '{query}' (tracking {len(targets)} targets)"


def remove_target(token: str, path: Path | str = THRESHOLDS_PATH) -> tuple[bool, str]:
    """Remove a target by 1-based index or by (case-insensitive) label match."""
    data = _load_raw(path)
    targets = data.get("targets", [])
    if not targets:
        return False, "no targets to remove"

    # numeric index?
    if token.strip().isdigit():
        idx = int(token.strip()) - 1
        if 0 <= idx < len(targets):
            removed = targets.pop(idx)
            _save_raw(data, path)
            return True, f"removed '{removed.get('label')}'"
        return False, f"index {token} out of range (1..{len(targets)})"

    norm = normalize(token)
    for i, t in enumerate(targets):
        if norm and norm in normalize(t.get("label", "")):
            removed = targets.pop(i)
            _save_raw(data, path)
            return True, f"removed '{removed.get('label')}'"
    return False, f"no target matching '{token}'"
