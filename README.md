# ArbitrageSniper

Selective arbitrage scanner for **used photography gear**. It monitors used
marketplaces in Romania and the EU, prices each listing against two benchmark
levels, and pushes a Telegram alert **only** when a deal clears a risk-zero
margin. Built to run unattended from GitHub Actions every 10–15 minutes.

> ⚠️ **Use responsibly.** Scraping may be restricted by a site's Terms of
> Service and by local law. You are responsible for respecting `robots.txt`,
> rate limits, and applicable regulations. This project is provided for
> educational/personal use; the polite delays and per-run caps are intentional.

## How it works

```
buy-side providers ──┐
 (OLX, Vinted,       │      ┌── MPB  (primary / floor "safety" price)
  Publi24, Wallapop) ├──▶  benchmarks ── eBay.de sold (secondary / retail target)
                     │      └── F64.ro used (secondary / retail reference)
                     ▼
            arbitrage engine  ──▶  Telegram alert  ──▶  SQLite (de-dup, committed by CI)
```

**Trigger rule (risk-zero):**

```
buy_price  ≤  mpb_price × MPB_MARGIN        (MPB_MARGIN default 0.90)
```

The 10% cushion covers shipping/fees. For every alert two spreads are computed:

| Metric            | Formula                                  | Meaning                 |
| ----------------- | ---------------------------------------- | ----------------------- |
| Risk-zero gain    | `MPB floor − buy price`                  | guaranteed exit via MPB |
| Potential gain    | `avg(eBay sold) − buy price`             | best-case resale margin |

All prices are normalised to EUR (see `arbitrage_sniper/currency.py`) before any
comparison, since providers report mixed RON/EUR.

## Project structure

```
.
├── main.py                          # orchestrator / entrypoint
├── thresholds.json                  # bridge config: targets + MPB ids / floors
├── requirements.txt
├── seen_ads.db                      # SQLite de-dup state (committed by the Action)
├── .env.example                     # local env template
├── .github/
│   └── workflows/
│       └── sniper.yml               # scheduled GitHub Action (cron */15)
├── tests/
│   └── test_arbitrage.py            # unit tests for the pure logic
└── arbitrage_sniper/
    ├── __init__.py
    ├── config.py                    # env-driven settings
    ├── models.py                    # Item / Benchmark / Alert dataclasses + parsers
    ├── currency.py                  # RON/USD/GBP → EUR normalisation
    ├── browser.py                   # async Playwright + stealth + UA rotation + jitter
    ├── database.py                  # SQLite manager (seen_ads + run_log)
    ├── arbitrage.py                 # core trigger + spread calculation (pure)
    ├── notifier.py                  # Telegram HTML notifier
    ├── providers/                   # BUY side
    │   ├── base.py
    │   ├── olx.py                   # olx.ro  (Cloudflare/Datadome → stealth browser)
    │   ├── vinted.py                # vinted.ro (warm cookies → internal JSON API)
    │   ├── publi24.py               # publi24.ro (DOM scrape)
    │   └── wallapop.py              # wallapop.com (warm cookies → search API)
    └── benchmarks/                  # VALUATION side
        ├── base.py
        ├── mpb.py                   # mpb.com/en-eu  (primary floor price)
        ├── ebay.py                  # ebay.de SOLD items (API or scrape)
        └── f64.py                   # f64.ro used section
```

## Standardised listing

Every provider returns the same dataclass (`arbitrage_sniper/models.py`):

```python
Item(id, title, price, link, platform, condition, image_url)
```

…plus optional enrichment (`currency`, `description`, `location`,
`seller_name`, `seller_is_new`) used for red-flag detection.

## Configuration

Set secrets/env (see `.env.example`):

| Variable             | Required | Purpose                                            |
| -------------------- | -------- | -------------------------------------------------- |
| `TELEGRAM_TOKEN`     | yes      | Bot token from @BotFather                          |
| `TELEGRAM_CHAT_ID`   | yes      | Target chat/channel id                             |
| `EBAY_APP_TOKEN`     | no       | eBay Browse API token (falls back to scraping)     |
| `MPB_MARGIN`         | no       | Trigger margin (default `0.90`)                    |
| `MIN_DELAY`/`MAX_DELAY` | no    | Random delay between requests (default 2–6 s)      |
| `HEADLESS`           | no       | `true` in CI, `false` to watch the browser locally |

Targets live in `thresholds.json`. Each entry maps search queries to an MPB id
(or full URL) and optional `mpb_floor` (EUR) used as a manual override/fallback.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
cp .env.example .env   # then fill in TELEGRAM_TOKEN / TELEGRAM_CHAT_ID

python main.py --dry-run   # sends a Telegram ping and exits
python main.py             # full scan
```

## GitHub Actions

`.github/workflows/sniper.yml` runs on a `*/15` cron (and manual dispatch),
installs Chromium, runs the scan, and commits the updated `seen_ads.db` back to
the repo so de-dup state survives between runs. Credentials come from
**GitHub Secrets** (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, optional
`EBAY_APP_TOKEN`).

## Tests

```bash
python -m pytest tests/ -q
```

The selectors used for scraping are best-effort and **will drift** as the target
sites change their markup; treat the provider/benchmark modules as maintained
templates rather than guaranteed-stable integrations.
