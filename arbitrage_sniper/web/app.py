"""FastAPI backend for the ArbitrageSniper dashboard.

It reads/writes the very same files the scanner uses:
  * ``thresholds.json`` -> the tracked targets (with price windows), and
  * ``seen_ads.db``     -> the scanned listings (name-matched, in/out of range).

So the UI is a thin, host-anywhere control panel over the existing state; the
GitHub Action keeps scanning and committing those files independently.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import ensure_data_files, settings
from ..database import Database
from ..providers import ALL_PROVIDERS
from ..targets import (
    Target,
    add_target,
    get_enabled_providers,
    load_targets,
    range_label,
    remove_target,
    set_enabled_providers,
    update_target,
)
from .scan_runner import runner

logger = logging.getLogger("arbitrage_sniper.web")

STATIC_DIR = Path(__file__).parent / "static"


async def _scheduler_loop(interval_min: int) -> None:
    """Periodically run a full scan on the always-on server (single-flight)."""
    await asyncio.sleep(20)  # let the server finish booting first
    while True:
        try:
            if not runner.running:
                logger.info("scheduler: starting periodic scan")
                runner.start(mode="all")
        except Exception:  # pragma: no cover - defensive
            logger.exception("scheduler tick failed")
        await asyncio.sleep(max(60, interval_min * 60))


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def lifespan(app: "FastAPI"):
    ensure_data_files()
    task = None
    if settings.scan_interval_min > 0:
        task = asyncio.create_task(_scheduler_loop(settings.scan_interval_min))
        logger.info("scheduler enabled: every %d min", settings.scan_interval_min)
    try:
        yield
    finally:
        if task:
            task.cancel()


app = FastAPI(title="ArbitrageSniper", version="1.0.0", lifespan=lifespan)

# Endpoints reachable without a token (the SPA shell + the auth probe).
_PUBLIC_API = {"/api/health"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Guard /api/* with a shared token when DASHBOARD_TOKEN is configured.

    Static assets (the SPA shell) stay public — they contain no secrets — so the
    browser can load the login screen; every data call requires the token.
    """
    path = request.url.path
    if settings.auth_required and path.startswith("/api/") and path not in _PUBLIC_API:
        provided = request.headers.get("x-auth-token")
        auth = request.headers.get("authorization", "")
        if not provided and auth.lower().startswith("bearer "):
            provided = auth[7:]
        if provided != settings.dashboard_token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "auth_required": settings.auth_required,
        "scheduler_min": settings.scan_interval_min,
        "version": app.version,
    }


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


class ProvidersUpdate(BaseModel):
    enabled: Optional[list[str]] = None  # None/empty => all enabled


class ScanRequest(BaseModel):
    mode: str = "all"  # "all" | "query"
    query: Optional[str] = None
    providers: Optional[list[str]] = None  # None => use enabled set


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


# --------------------------------------------------------------------------- #
# API: providers + on-demand scan
# --------------------------------------------------------------------------- #
def _provider_available(name: str) -> bool:
    if name == "facebook":
        return bool(settings.facebook_cookies_path)
    return True


@app.get("/api/providers")
def list_providers() -> dict:
    enabled = get_enabled_providers()  # None => all enabled
    out = []
    for p in ALL_PROVIDERS:
        out.append({
            "name": p.name,
            "label": getattr(p, "label", p.name),
            "available": _provider_available(p.name),
            "enabled": True if enabled is None else (p.name in enabled),
        })
    return {"providers": out}


@app.post("/api/providers")
def update_providers(payload: ProvidersUpdate) -> dict:
    changed, msg = set_enabled_providers(payload.enabled)
    return {"ok": changed, "message": msg}


@app.post("/api/scan", status_code=202)
async def start_scan(payload: ScanRequest) -> dict:
    # async so runner.start() can schedule the background task on the running loop.
    ok, msg = runner.start(
        mode=payload.mode, query=payload.query, providers=payload.providers
    )
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    return {"ok": True, "message": msg, "status": runner.snapshot()}


@app.get("/api/scan")
def scan_status() -> dict:
    return runner.snapshot()


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
