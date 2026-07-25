"""FastAPI backend for the ArbitrageSniper dashboard.

It reads/writes the very same files the scanner uses:
  * ``thresholds.json`` -> the tracked targets (with price windows), and
  * ``seen_ads.db``     -> the scanned listings (name-matched, in/out of range).

So the UI is a thin, host-anywhere control panel over the existing state; the
GitHub Action keeps scanning and committing those files independently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..database import Database
from ..targets import (
    Target,
    add_target,
    load_targets,
    range_label,
    remove_target,
    update_target,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="ArbitrageSniper", version="1.0.0")


# --------------------------------------------------------------------------- #
# request models
# --------------------------------------------------------------------------- #
class TargetCreate(BaseModel):
    query: str
    price_min: Optional[float] = None
    price_max: Optional[float] = None


class TargetUpdate(BaseModel):
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    mpb_id: Optional[str] = None
    mpb_floor: Optional[float] = None
    channel: Optional[str] = None
    # Explicit "clear the field" support: send these to null them out.
    clear_price_min: bool = False
    clear_price_max: bool = False


# --------------------------------------------------------------------------- #
# serialization helpers
# --------------------------------------------------------------------------- #
def _target_to_api(index: int, t: Target) -> dict:
    return {
        "index": index,
        "id": t.label,
        "label": t.label,
        "queries": t.queries,
        "price_min": t.price_min,
        "price_max": t.price_max,
        "price_label": range_label(t.price_min, t.price_max),
        "mpb_id": t.mpb_id,
        "mpb_floor": t.mpb_floor,
        "channel": t.channel,
        "chat_id": t.chat_id,
        "topic_id": t.topic_id,
        "include": t.effective_include,
        "exclude": t.exclude_terms,
    }


def _db() -> Database:
    return Database()


# --------------------------------------------------------------------------- #
# API: targets
# --------------------------------------------------------------------------- #
@app.get("/api/targets")
def list_targets() -> dict:
    targets = load_targets()
    return {"targets": [_target_to_api(i, t) for i, t in enumerate(targets)]}


@app.post("/api/targets", status_code=201)
def create_target(payload: TargetCreate) -> dict:
    changed, msg = add_target(payload.query, payload.price_min, payload.price_max)
    if not changed:
        raise HTTPException(status_code=409, detail=msg)
    return {"ok": True, "message": msg}


@app.patch("/api/targets/{identifier}")
def patch_target(identifier: str, payload: TargetUpdate) -> dict:
    updates: dict = {}
    if payload.clear_price_min:
        updates["price_min"] = None
    elif payload.price_min is not None:
        updates["price_min"] = payload.price_min
    if payload.clear_price_max:
        updates["price_max"] = None
    elif payload.price_max is not None:
        updates["price_max"] = payload.price_max
    for key in ("mpb_id", "mpb_floor", "channel"):
        value = getattr(payload, key)
        if value is not None:
            updates[key] = value
    if not updates:
        raise HTTPException(status_code=400, detail="no changes provided")
    changed, msg = update_target(identifier, updates)
    if not changed:
        raise HTTPException(status_code=404, detail=msg)
    return {"ok": True, "message": msg}


@app.delete("/api/targets/{identifier}")
def delete_target(identifier: str) -> dict:
    changed, msg = remove_target(identifier)
    if not changed:
        raise HTTPException(status_code=404, detail=msg)
    return {"ok": True, "message": msg}


# --------------------------------------------------------------------------- #
# API: scanned items
# --------------------------------------------------------------------------- #
@app.get("/api/items")
def list_items(
    target: Optional[str] = None,
    in_range: Optional[bool] = None,
    alerted: Optional[bool] = None,
    platform: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "last_seen",
    desc: bool = True,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    db = _db()
    try:
        items = db.list_items(
            target=target, in_range=in_range, alerted=alerted, platform=platform,
            q=q, sort=sort, descending=desc, limit=limit, offset=offset,
        )
        total = db.count_items(
            target=target, in_range=in_range, alerted=alerted, platform=platform, q=q
        )
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        db.close()


@app.get("/api/filters")
def filters() -> dict:
    db = _db()
    try:
        return {"targets": db.distinct_targets(), "platforms": db.distinct_platforms()}
    finally:
        db.close()


@app.get("/api/stats")
def stats() -> dict:
    db = _db()
    try:
        s = db.stats()
    finally:
        db.close()
    s["total_targets"] = len(load_targets())
    return s


@app.post("/api/clear")
def clear(q: Optional[str] = None) -> dict:
    db = _db()
    try:
        removed = db.clear_seen(q or None)
    finally:
        db.close()
    return {"ok": True, "removed": removed}


# --------------------------------------------------------------------------- #
# static SPA
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
