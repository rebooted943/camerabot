# Prompt — Turn ArbitrageSniper into a Mobile App

> Copy everything inside the fenced block below and hand it to a capable AI
> coding agent (Cursor, Claude Code, etc.). It is written to be self-contained:
> the agent should not need to ask clarifying questions to get started.
>
> This document is the *spec/prompt* only — it does not change the running
> system. Keep it in sync if the backend API evolves.

---

```prompt
ROLE
You are a Senior Mobile Engineer (React Native / Expo + TypeScript) and Senior
Product/UX Designer. You build production-grade, store-ready cross-platform
apps with clean architecture, strong typing, tests, and CI/CD.

CONTEXT — THE EXISTING SYSTEM ("ArbitrageSniper")
ArbitrageSniper is a Python system that scans second-hand marketplaces for
under-priced photography gear and flags "risk-zero" deals. It already has:
- A scanner engine (async Playwright + stealth) with pluggable buy-side
  PROVIDERS (Subito.it, eBay.it, Back Market, Facebook Marketplace, OLX.ro,
  Publi24.ro, Vinted EU) and valuation BENCHMARKS (MPB floor price, eBay sold
  average, F64 retail).
- A selective arbitrage engine: alert when buy_price <= mpb_price * MARGIN
  (default 0.90) with a MAX_GAIN sanity cap, OR when a per-target PRICE WINDOW
  [min,max] matches. Two spreads are computed: risk-zero gain (MPB) and
  potential gain (eBay sold).
- Relevance matching that filters accessories ("battery grip", "charger") and
  wrong models (A7 II vs A7 III, EOS 1300D vs R6) using word-boundary rules.
- SQLite state (`seen_ads.db`) recording EVERY name-matched listing, with an
  `in_range` flag so out-of-range items are still stored/visible.
- A Telegram bot (commands: /scan, /search, /add <query> [min-max], /remove,
  /list, /clear, /help) and per-target routing to Telegram channels/topics.
- A FastAPI + vanilla-JS web dashboard exposing a REST API (see CONTRACT).
- GitHub Actions: scheduled scans (cron), a Telegram command poller, and a
  read-only GitHub Pages publish of the dashboard.

Assume you have read access to the repository. Reuse the existing REST API and
data model; do NOT reimplement the scraping engine on the client.

GOAL
Ship a cross-platform (iOS + Android) mobile app that has FULL FEATURE PARITY
with the web dashboard and Telegram bot, plus the mobile-native additions
listed below. The app is the primary control surface: manage what is tracked,
trigger scans, browse results, and receive real-time deal alerts.

TECH STACK (use unless you have a strong, documented reason not to)
- Expo (React Native) + TypeScript. Expo Router for navigation.
- State/data: TanStack Query (server cache) + Zustand (local UI state).
- UI: a single design system (e.g. Tamagui or React Native Paper) with a
  custom dark/light theme matching the web app's palette
  (bg #0b0f17, elevated #131a26, accent #4f8cff, success #22c98b, warn #ffb020,
  danger #ff5d6c). Rounded cards, subtle shadows, responsive to phone + tablet.
- Forms/validation: react-hook-form + zod.
- Notifications: Expo Notifications (push) + FCM/APNs.
- Storage/offline: MMKV or expo-secure-store for secrets; React Query
  persistence for offline cache.
- Charts: victory-native or react-native-svg for price history.
- i18n: i18next with English + Italian (the primary user is Italian).
- Testing: Jest + React Native Testing Library; Detox or Maestro for e2e.
- CI/CD: EAS Build + EAS Submit; GitHub Actions workflow for lint/test/build.

BACKEND / HOSTING (critical — a mobile app needs an always-on API)
The current FastAPI app is meant to run locally and the scanner runs in GitHub
Actions (not always-on). You must make the API reachable by the app:
1. Package the FastAPI backend as a small always-on service (Dockerfile) and
   document deployment to a free/low-cost host (Fly.io, Render, Railway, or a
   VPS). The scanner can keep running in GitHub Actions and commit `seen_ads.db`,
   while the API service reads that state; OR run the scanner on the same host
   via a scheduler. Pick one, document the trade-offs, and implement it.
2. Add AUTHENTICATION to the API (it is currently open): token- or
   OAuth-device-code-based, with a bearer token stored in secure storage on the
   device. Never embed long-lived secrets in the app bundle.
3. Add a lightweight "push token registration" endpoint and deliver deal alerts
   as native push notifications (in addition to the existing Telegram path).
4. Keep everything backward compatible: the web dashboard and Telegram bot must
   continue to work unchanged.

FEATURE PARITY (must-have — mirror the web app + Telegram)
- Targets: list, add (with optional price window min/max EUR), edit price range
  inline, remove. Adding accepts natural input like "Sony A7 III 400-700",
  "Canon R6 <900", ">300".
- Scanned items: infinite/paged list AND card/grid views with image thumbnails,
  price, MPB/eBay/F64 context, risk-zero + potential gain, badges
  (alerted / in-range / out-of-range / platform), and a link that opens the
  listing (in-app browser + "open externally"). Filters: target, platform,
  in/out of range, alerted-only, free-text search; sort by newest / cheapest /
  best gain.
- Scan now: trigger a scan (all targets OR a one-off query) and show live status
  (running → done/error) with counts (scanned / new / alerts).
- Sources: per-provider on/off toggles (persisted), so a scan can hit a single
  marketplace; show "needs setup" state for providers requiring credentials.
- Stats header: targets / scanned / in-range / alerts.
- Clear: forget seen ads (all or matching a query) so the next scan re-notifies.
- Telegram-equivalent alerting via native push, with the same content
  (title, price, MPB/eBay context, gains, red flags, link).

MOBILE-NATIVE ADDITIONS (add these — they materially improve the product)
- Rich push notifications with deep links straight to the deal; notification
  actions ("Open listing", "Snooze", "Not interested").
- Watchlist / favorites and "hide/dismiss" per listing.
- Price-history sparkline per target (persist benchmark values over time; add a
  small time-series table server-side if needed) and per-listing price drops.
- Saved filter presets and per-target notification preferences (mute, min-gain
  threshold).
- Pull-to-refresh, skeleton loaders, empty/error states, optimistic updates.
- Offline mode: last-synced items/targets viewable without network.
- Onboarding flow (connect to backend URL + sign in, enable notifications).
- Biometric app lock (Face ID / fingerprint) and secure token storage.
- Share a deal (system share sheet) and copy link.
- Localization: full IT + EN; currency/locale-aware formatting.
- Accessibility: dynamic type, sufficient contrast, screen-reader labels.
- Settings: backend URL, theme, language, notification prefs, sign out.

API CONTRACT (already implemented on the FastAPI backend — reuse it)
Base: the FastAPI service. JSON. Add auth headers per the AUTH task above.
- GET    /api/stats            -> { total_seen, total_alerted, total_in_range, total_targets }
- GET    /api/targets          -> { targets: [{ index,id,label,queries,price_min,price_max,price_label,mpb_id,mpb_floor,channel,chat_id,topic_id,include,exclude }] }
- POST   /api/targets          <- { query, price_min?, price_max? }
- PATCH  /api/targets/{id}     <- { price_min?, price_max?, mpb_id?, mpb_floor?, channel?, clear_price_min?, clear_price_max? }
- DELETE /api/targets/{id}
- GET    /api/items            ?target&in_range&alerted&platform&q&sort&desc&limit&offset
                               -> { items:[...], total, limit, offset }
- GET    /api/filters          -> { targets:[...], platforms:[...] }
- GET    /api/providers        -> { providers:[{ name,label,available,enabled }] }
- POST   /api/providers        <- { enabled:[names] | null }
- POST   /api/scan             <- { mode:"all"|"query", query?, providers?:[names] }  (202)
- GET    /api/scan             -> { state:"idle"|"running"|"done"|"error", message, scanned, new, alerts, error }
- POST   /api/clear            ?q
NEW endpoints you must add server-side (keep style/conventions consistent):
- POST   /api/auth/... (device login / token issue)
- POST   /api/push/register    <- { token, platform }        (store Expo push token)
- GET    /api/targets/{id}/history  -> benchmark price history (add a table)
Item shape: { unique_key, platform, ad_id, title, price, currency, link,
  image_url, condition, location, alerted, in_range, mpb_price, ebay_price,
  f64_price, safe_gain, reason, first_seen, last_seen }.

ARCHITECTURE & QUALITY REQUIREMENTS
- Clean layering: api client (typed, generated from the OpenAPI schema at
  /openapi.json where possible) → data hooks (React Query) → screens/components.
- Strong typing end-to-end; no `any`. Centralized error handling + toasts.
- Handle the `/api/scan` long-running job with polling (or SSE/websocket if you
  add it server-side) and background-safe UI.
- Feature-flag the native additions so parity ships first.
- Secrets only in secure storage / EAS secrets; never committed.

DELIVERABLES
1. A new `mobile/` app in the repo (Expo + TS) with the screens above.
2. A `Dockerfile` + deploy docs for the always-on API, plus the AUTH and PUSH
   endpoints implemented in the existing FastAPI app (and tests for them).
3. A typed API client + React Query hooks.
4. Unit tests for critical logic and at least one e2e happy-path (add target →
   scan → see alert → open listing).
5. EAS build config + a GitHub Actions workflow that lints, tests, and builds.
6. README for `mobile/`: setup, env (`API_BASE_URL`, auth), run on device,
   build, and store-submission notes.
7. Updated top-level README linking to the mobile app.

DEFINITION OF DONE
- App runs on iOS and Android (Expo Go for dev + a dev build for push).
- Every web/Telegram feature is reachable and works against the live API.
- Push notifications deliver a deal alert end-to-end on a physical device.
- All new server endpoints have tests; existing `pytest` suite still passes.
- Lint/type-check/test are green in CI; EAS build succeeds.

CONSTRAINTS & GUARDRAILS
- Do NOT break the web dashboard, Telegram bot, or GitHub Actions.
- Do NOT scrape from the phone; the app only talks to the backend API.
- Respect each marketplace's ToS and rate limits (unchanged from the engine).
- Keep the design consistent with the existing dark theme; support light mode.
- Prefer incremental PRs: (1) API auth+push+hosting, (2) app scaffold + parity,
  (3) native additions. Explain each step and keep commits focused.

OUTPUT
Work autonomously. Produce code, migrations, tests, and docs. When you finish a
milestone, summarize what changed, how to run it, and what remains. Ask for a
decision ONLY if a choice has irreversible cost (e.g., paid hosting tier).
```

---

## Notes for whoever runs this prompt

- The mobile app depends on **one always-on backend**. The current
  `arbitrage_sniper/web` FastAPI app is the base; the biggest net-new work is
  **hosting it and adding auth + push**, since GitHub Actions alone cannot serve
  a live API.
- Feature parity is defined against the REST contract in
  `arbitrage_sniper/web/app.py`. If you change those endpoints, update the
  `API CONTRACT` section above so the prompt stays accurate.
- Suggested first milestone to de-risk: deploy the API + auth, then build the
  app scaffold that reads `/api/stats` and `/api/items`.
