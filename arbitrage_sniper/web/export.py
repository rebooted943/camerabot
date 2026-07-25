"""Export current state to a static ``data.json`` for the GitHub Pages site.

The online dashboard is read-only: a workflow runs this after each scan and
publishes the SPA + this JSON to GitHub Pages, so results are viewable from
anywhere without a running backend.

Usage:
    python -m arbitrage_sniper.web.export site/data.json [--limit 500]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from ..database import Database
from ..providers import ALL_PROVIDERS
from ..targets import get_enabled_providers, load_targets, range_label


def build_payload(limit: int = 500) -> dict:
    db = Database()
    try:
        items = db.list_items(limit=limit)
        stats = db.stats()
        platforms = db.distinct_platforms()
        target_names = db.distinct_targets()
    finally:
        db.close()

    enabled = get_enabled_providers()
    providers = [
        {
            "name": p.name,
            "label": getattr(p, "label", p.name),
            "enabled": True if enabled is None else (p.name in enabled),
        }
        for p in ALL_PROVIDERS
    ]

    targets = []
    for i, t in enumerate(load_targets()):
        targets.append({
            "index": i,
            "id": t.label,
            "label": t.label,
            "queries": t.queries,
            "price_min": t.price_min,
            "price_max": t.price_max,
            "price_label": range_label(t.price_min, t.price_max),
            "mpb_floor": t.mpb_floor,
            "channel": t.channel,
        })

    stats["total_targets"] = len(targets)
    return {
        "generated_at": int(time.time()),
        "readonly": True,
        "stats": stats,
        "targets": targets,
        "providers": providers,
        "filters": {"targets": target_names, "platforms": platforms},
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export dashboard data to JSON")
    parser.add_argument("out", help="output path, e.g. site/data.json")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    payload = build_payload(limit=args.limit)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out} ({len(payload['items'])} items, {len(payload['targets'])} targets)")


if __name__ == "__main__":
    main()
