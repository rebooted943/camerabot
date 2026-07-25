# ArbitrageSniper — Development Roadmap

This document captures where the project is today and where it can go, with an
explicit path to **expand beyond photography gear** into other resale markets.

Phases below are ordered by capability and dependency, **not by calendar time**.
Each item notes the components it touches and the main risks, so work can be
sequenced by effort/impact rather than dates.

---

## 1. Current state (baseline)

- **Engine:** async Playwright + stealth scraper with pluggable buy-side
  providers (Subito, eBay.it, Back Market, Facebook Marketplace, OLX, Publi24,
  Vinted EU) and valuation benchmarks (MPB floor, eBay sold avg, F64 retail).
- **Decision logic:** MPB risk-zero trigger (`buy <= mpb * margin`, gain cap) OR
  per-target price window `[min, max]`; two spreads (risk-zero + potential).
- **Relevance matching:** word-boundary include/exclude that drops accessories
  and wrong models.
- **State:** SQLite `seen_ads.db` storing every name-matched listing (with
  `in_range`), committed by CI for de-dup persistence.
- **Interfaces:** Telegram bot (commands + channel/topic routing), FastAPI +
  SPA dashboard (targets CRUD, price windows, scanned-items browser, Scan-now,
  source selection), read-only GitHub Pages publish.
- **Automation:** GitHub Actions (scheduled scan, Telegram poller, Pages).

---

## 2. Roadmap by theme

### Theme A — Reliability & anti-bot hardening
*Touches:* `browser.py`, providers.
- Proxy rotation (residential/mobile pools) + per-domain rate governor.
- Session/cookie persistence per marketplace; captcha/Datadome handling
  strategy and automatic backoff/retry with circuit breakers per provider.
- Health checks per provider (selector-drift detection) that alert when a source
  starts returning 0 results, so scrapers are fixed before deals are missed.
- Move from best-effort CSS selectors to resilient extraction (JSON endpoints,
  schema.org, or a small parser layer per site).
*Risk:* ToS/anti-bot arms race; legal exposure — see §4.

### Theme B — Data quality & valuation
*Touches:* `benchmarks/`, `matching.py`, `currency.py`.
- Live FX rates (cache) instead of static constants.
- Confidence scoring on benchmarks (sample size, dispersion) surfaced in alerts.
- Condition-aware pricing (map each listing's condition to the right MPB grade).
- A price-history time series (per target/model) enabling trend + drop alerts.
- Deduplicate the *same* physical item reposted across marketplaces.

### Theme C — Decision engine & ML
*Touches:* `arbitrage.py`, new model service.
- Learn a price model per model/category from historical sold data instead of a
  single benchmark; predict fair value + probability of profit.
- Rank deals by expected net margin after fees/shipping/tax, not raw spread.
- Anomaly detection for scams (too-good-to-be-true, stock photos, new sellers).
- Image-based matching/verification (is the photo actually the claimed model?).

### Theme D — Notifications & UX
*Touches:* `notifier.py`, web, mobile.
- The mobile app (see `MOBILE_APP_PROMPT.md`) with native push.
- Digestible summaries, per-target mute/threshold, and "why this alerted".
- One-tap actions (dismiss, watch, mark bought) that feed back into ranking.

### Theme E — Platform & multi-user (SaaS)
*Touches:* backend, DB, auth.
- Always-on hosted API + authentication (prerequisite for mobile & SaaS).
- Multi-tenant data model (users own targets/alerts/notification channels).
- Move state from a git-committed SQLite file to a managed DB (Postgres) once
  concurrency/scale outgrows the single-file model.
- Usage metering + billing if offered as a product.

### Theme F — Observability & ops
- Structured logging, run metrics dashboard (already have `run_log`), and
  per-provider success/latency metrics.
- Alerting on pipeline failures (not just deals).

---

## 3. Expanding beyond photography (multi-vertical)

The core insight — *"scan marketplaces, value each item against reliable
benchmarks, alert on positive spread"* — is **category-agnostic**. Turning
ArbitrageSniper into a general resale-arbitrage platform mainly means
generalizing three things that are currently photo-specific.

### 3.1 Generalize the data model
- Introduce a **`Category` / vertical** concept (e.g. `photography`,
  `electronics`, `watches`, `sneakers`, `bicycles`, `music-gear`,
  `luxury/handbags`, `game-consoles`, `power-tools`, `car-parts`).
- Each target belongs to a category; `thresholds.json` gains a `category` field
  and a top-level `categories` registry. Relevance rules, benchmark providers,
  and notification routing can be configured per category.
- Add a lightweight **catalog/taxonomy** (brand → model → variant) per vertical
  so matching and price history key off canonical model IDs, not free text.

### 3.2 Make benchmarks pluggable per vertical
Photography uses MPB/eBay/F64. Each new vertical needs its own "floor" and
"retail" references. The `BaseBenchmark` abstraction already supports this — add
providers such as:
- **Electronics/phones:** Back Market, Swappa, eBay sold, Amazon Renewed.
- **Watches:** Chrono24, WatchCharts, eBay sold.
- **Sneakers:** StockX / GOAT last-sale, eBay sold.
- **Bicycles:** BuyCycle, The Pro's Closet, eBay sold.
- **Music gear:** Reverb price guide, eBay sold.
- **Generic fallback:** eBay/Amazon sold-median as a universal retail benchmark.
Design a **benchmark registry keyed by category**, with graceful fallback to the
generic eBay-sold benchmark when no specialized source exists.

### 3.3 Generalize relevance & providers
- The word-boundary matcher is already generic; per-category default exclude
  lists (accessories/parts vary by vertical) and include/alias dictionaries.
- Buy-side providers are mostly category-agnostic marketplaces (OLX, Vinted,
  Wallapop, Subito, Marketplace, Kleinanzeigen, Leboncoin, Mercari). Add new
  geos/marketplaces as pluggable providers; scope each scan by category so only
  relevant queries run.

### 3.4 New verticals — sequencing by effort/impact
Recommended order (low incremental effort → reuses existing infra):
1. **Phones / consumer electronics** — huge volume, Back Market + eBay-sold
   benchmarks already partly present; minimal new code.
2. **Game consoles / GPUs** — high churn, clear model taxonomy, eBay-sold works.
3. **Watches** — high ticket, strong specialized benchmarks (Chrono24), but
   condition/authenticity risk is higher.
4. **Sneakers** — StockX/GOAT give near-perfect benchmarks; sizing adds a
   matching dimension.
5. **Bicycles / e-bikes, music gear, power tools** — solid benchmarks, regional.
Each vertical = a category config + 1–2 benchmark providers + an exclude/alias
dictionary; the engine, dedup, notifications, dashboard, and mobile app are
reused unchanged.

### 3.5 Cross-cutting for scale
- **Taxonomy service** to normalize titles → canonical models across verticals.
- **Fees/shipping/tax model per marketplace & country** so ranking reflects true
  net margin (essential once expanding geographies).
- **Localization** of currencies, languages, and marketplaces per region.

---

## 4. Risks, constraints & mitigations
- **Legal / ToS:** scraping and anti-bot evasion may violate site terms and
  local law. Mitigate with official APIs where available (eBay, Back Market,
  Reverb, StockX partner APIs), rate limiting, `robots.txt` respect, and clear
  personal-use positioning until a compliant commercial model is validated.
- **Anti-bot fragility:** selectors and defenses change; invest in Theme A
  health checks and API-first sourcing.
- **Data accuracy:** bad benchmarks create false positives; invest in Theme B
  confidence scoring before scaling verticals.
- **Scale:** git-committed SQLite is fine for a single user; multi-user/SaaS
  requires the Theme E managed-DB migration.

---

## 5. Suggested next steps (highest leverage first)
1. **Host the API + add auth + push** (unblocks the mobile app and SaaS).
2. **Add a `category` abstraction + benchmark registry** (unblocks multi-vertical
   with minimal engine changes).
3. **Ship phones/electronics as the second vertical** to validate the
   generalization end-to-end.
4. **Add price history + net-margin ranking** to improve alert quality.
5. **Harden anti-bot + provider health checks** to keep sources alive as you
   scale breadth.
