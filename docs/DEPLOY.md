# Deploy the always-on dashboard (Option A)

This turns the dashboard into a **fully interactive online app**: add/remove
searches, set price windows, choose sources, and **force scans with filters** —
all from a public URL, not just locally. It runs the API + SPA + scanner in one
self-contained container with persistent state on a volume.

Why a host (and not GitHub Pages): Pages is static, so it can only *show*
results. A live backend is required to run Playwright scans and accept writes.
You still deploy **from the GitHub repo** (Render/Fly build from it on push).

## What the container does

- Serves the SPA in **live mode** (all controls enabled).
- Exposes the REST API (`/api/targets`, `/api/items`, `/api/providers`,
  `/api/scan`, …), protected by a shared token.
- Runs scans **in-process**: the "Scan now" button and an optional built-in
  scheduler (`SCAN_INTERVAL_MIN`). Chromium is preinstalled in the image.
- Stores `seen_ads.db` + `thresholds.json` on the mounted volume `/data`
  (seeded from the repo's `thresholds.json` on first boot).

## Environment variables

| Var | Purpose |
| --- | --- |
| `DASHBOARD_TOKEN` | **Set this.** Shared token; the SPA asks for it. Empty ⇒ API open. |
| `DATA_DIR` | State dir (the volume mount, e.g. `/data`). |
| `SCAN_INTERVAL_MIN` | Built-in periodic scan interval (minutes). `0` = manual only. |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | Optional: push deal alerts to Telegram. |
| `EBAY_APP_TOKEN` | Optional: eBay Browse API (else scraping). |
| `FACEBOOK_COOKIES_PATH` | Optional: enable Facebook Marketplace. |
| `HEADLESS` | `true` in containers. |

---

## Option 1 — Render (Blueprint)

1. Push this repo to GitHub (already done).
2. Render → **New → Blueprint** → pick the repo. It reads `render.yaml`.
3. Set secrets when prompted: `DASHBOARD_TOKEN`, `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID` (and `EBAY_APP_TOKEN` if you have one).
4. Deploy. Open the service URL → enter your `DASHBOARD_TOKEN`.

Note: the persistent disk in `render.yaml` requires a paid instance type.

## Option 2 — Fly.io

```bash
fly launch --no-deploy                 # uses the bundled fly.toml
fly volumes create as_data --size 1 --region cdg
fly secrets set DASHBOARD_TOKEN=xxxx TELEGRAM_TOKEN=xxxx TELEGRAM_CHAT_ID=xxxx
fly deploy
fly open
```

## Option 3 — Any Docker host (VPS / Railway / Docker Compose)

```bash
docker build -t arbitragesniper .
docker run -d --name sniper -p 8000:8000 \
  -v sniper_data:/data \
  -e DASHBOARD_TOKEN=xxxx \
  -e SCAN_INTERVAL_MIN=30 \
  -e TELEGRAM_TOKEN=xxxx -e TELEGRAM_CHAT_ID=xxxx \
  arbitragesniper
# open http://<host>:8000
```

---

## Using it online

- First load asks for the **access token** (`DASHBOARD_TOKEN`); it's stored in
  the browser and sent on every API call.
- **Add / remove targets** with a price window, **edit ranges**, **toggle
  sources**, and hit **Scan now** (all targets or a one-off query) — with live
  progress. Everything the local dashboard does, now online.

## Relationship with GitHub Actions & Pages

- Once you run the hosted app, **it is the source of truth** (state on the
  volume). It scans on its own (button + scheduler), so you can **disable the
  scheduled `ArbitrageSniper` workflow** to avoid two independent scanners.
- The Telegram bot/poller and the read-only GitHub Pages viewer remain optional
  and independent (they use the repo's committed copy of the state).

## Security notes

- Always set `DASHBOARD_TOKEN` for a public deployment.
- Secrets go in the host's env/secret store — never in the repo or the image.
- Put the service behind HTTPS (Render/Fly do this automatically).
