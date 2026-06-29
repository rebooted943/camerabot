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
 (Subito, eBay.it,   │      ┌── MPB  (primary / floor "safety" price)
  Back Market, FB,    ├──▶  benchmarks ── eBay.de sold (secondary / retail target)
  OLX, Publi24,      │      └── F64.ro used (secondary / retail reference)
  Vinted EU)         ▼
            arbitrage engine  ──▶  Telegram alert  ──▶  SQLite (de-dup, committed by CI)
```

**Trigger rule (risk-zero):**

```
buy_price ≤ mpb_price × MPB_MARGIN     AND     gain% ≤ MAX_GAIN_PCT
            (MPB_MARGIN default 0.90)                  (default 500%)
```

The 10% cushion covers shipping/fees. The `MAX_GAIN_PCT` guard drops
"too-good-to-be-true" listings (scams / mis-parsed prices / part-outs). For
every alert two spreads are computed:

| Metric            | Formula                                  | Meaning                 |
| ----------------- | ---------------------------------------- | ----------------------- |
| Risk-zero gain    | `MPB floor − buy price`                  | guaranteed exit via MPB |
| Potential gain    | `avg(eBay sold) − buy price`             | best-case resale margin |

All prices are normalised to EUR (see `arbitrage_sniper/currency.py`) before any
comparison, since providers report mixed RON/EUR.

**Relevance filter.** Every listing (and every benchmark sample) is checked
against per-target match rules (`arbitrage_sniper/matching.py`) so accessories
("battery grip", "charger") and wrong models ("A7 II", "EOS 1300D") are dropped.
Matching uses word-boundary regexes, so `iii` is never matched by an `ii` rule
and `a7` never matches `a7r`.

## Project structure

```
.
├── main.py                          # orchestrator / entrypoint
├── thresholds.json                  # bridge config: targets + MPB ids / floors
├── requirements.txt
├── seen_ads.db                      # SQLite de-dup state (committed by the Action)
├── .env.example                     # local env template
├── scripts/
│   └── get_chat_id.py               # helper to discover TELEGRAM_CHAT_ID
├── .github/
│   └── workflows/
│       ├── sniper.yml               # scheduled scan (cron */15)
│       ├── commands.yml             # Telegram command poller (cron */5)
│       └── ci.yml                   # runs pytest on push/PR
├── tests/
│   ├── test_arbitrage.py            # pure trigger/spread logic
│   └── test_matching.py             # relevance + gain cap + aggregation
└── arbitrage_sniper/
    ├── __init__.py
    ├── config.py                    # env-driven settings
    ├── models.py                    # Item / Benchmark / Alert dataclasses + parsers
    ├── matching.py                  # relevance matching (accessories/wrong models)
    ├── targets.py                   # Target model + thresholds.json add/remove/list
    ├── commands.py                  # Telegram command parser
    ├── currency.py                  # RON/USD/GBP → EUR normalisation
    ├── browser.py                   # async Playwright + stealth + UA rotation + jitter
    ├── database.py                  # SQLite manager (seen_ads + run_log + bot_state)
    ├── arbitrage.py                 # core trigger + spread calculation (pure)
    ├── notifier.py                  # Telegram HTML notifier + getUpdates
    ├── providers/                   # BUY side (Italy + Romania only)
    │   ├── base.py
    │   ├── subito.py                # subito.it
    │   ├── ebay_it.py               # ebay.it active listings
    │   ├── backmarket.py            # backmarket.it refurbished gear
    │   ├── facebook.py              # Facebook Marketplace (IT + RO cities)
    │   ├── olx.py                   # olx.ro
    │   ├── publi24.py               # publi24.ro
    │   └── vinted.py                # all EU Vinted storefronts (west + east)
    │       └── vinted_markets.py    # country domain registry
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

Need the chat id? Send `/start` to your bot in Telegram, then run:

```bash
TELEGRAM_TOKEN=123:abc python scripts/get_chat_id.py
```

Set secrets/env (see `.env.example`):

| Variable             | Required | Purpose                                            |
| -------------------- | -------- | -------------------------------------------------- |
| `TELEGRAM_TOKEN`     | yes      | Bot token from @BotFather                          |
| `TELEGRAM_CHAT_ID`   | yes      | Target chat/channel id                             |
| `EBAY_APP_TOKEN`     | no       | eBay Browse API token (falls back to scraping)     |
| `FACEBOOK_COOKIES_PATH` | no    | Path to Playwright cookies JSON for FB Marketplace |
| `VINTED_REGIONS`     | no       | `west`, `east`, or `west,east` (default: both)     |
| `VINTED_MARKETS`     | no       | Override: comma codes e.g. `it,ro,fr,pl,de`        |
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

## Telegram commands

Send these messages to the bot; the `commands.yml` poller (cron `*/5`) picks
them up and replies in chat:

| Command                  | Effect                                                   |
| ------------------------ | -------------------------------------------------------- |
| `/scan`                  | Run a full scan of all tracked targets now               |
| `/scan <query>`          | One-off scan for a query, e.g. `/scan fujifilm x-t50`    |
| `/search <query>`        | Alias of `/scan <query>`                                 |
| `/add <query>`           | Add a target to the watch list (persisted + committed)   |
| `/remove <query \| #>`   | Remove a target by name or list index                    |
| `/list`                  | Show tracked targets                                     |
| `/clear [query]`         | Forget seen ads (all, or matching a query) so the next scan re-notifies them |
| `/help`                  | Show the command help                                    |

Only the chat id in `TELEGRAM_CHAT_ID` is allowed to issue commands. Response
latency depends on the poll interval plus GitHub's scheduled-run delay; you can
also trigger a scan immediately from **Actions → run workflow** (with an optional
`query` input). One-off `/search` scans use MPB search as the floor benchmark; if
MPB has no price they still reply with the cheapest matching listings.

## Routing alerts to channels / topics

By default every alert goes to `TELEGRAM_CHAT_ID`. To filter gear by
category in Telegram you can route each target to its own channel or to a
**forum topic** (a supergroup with *Topics* enabled). Define named channels in
`thresholds.json` and point targets at them:

```json
{
  "channels": {
    "sony":  { "chat_id": "-1001234567890", "topic_id": 12 },
    "canon": { "chat_id": "-1001234567890", "topic_id": 14 }
  },
  "targets": [
    { "label": "Sony A7 III (body)", "queries": ["Sony A7 III"], "channel": "sony" },
    { "label": "Canon EOS R6 (body)", "queries": ["Canon EOS R6"], "channel": "canon" }
  ]
}
```

- `chat_id` is a channel/group id (e.g. `-100…`); the bot must be an admin there.
- `topic_id` is the forum-topic thread id (`message_thread_id`); omit it to post
  to the channel/group root.
- A target may also set `chat_id`/`topic_id` directly instead of using a named channel.
- Discover both ids with `scripts/get_chat_id.py` (it prints chat ids and any
  forum topic ids it sees).

## Run a single query locally

```bash
python main.py --query "Nikon Z6 II"   # scrape + benchmark + reply once
python main.py --listen                 # process pending Telegram commands
```

## GitHub Actions

- `sniper.yml` runs on a `*/15` cron (and manual dispatch), installs Chromium,
  runs the scan, and commits the updated `seen_ads.db` back to the repo so
  de-dup state survives between runs.
- `commands.yml` runs on a `*/5` cron and processes Telegram commands; it commits
  both `seen_ads.db` and `thresholds.json` (so `/add` and `/remove` persist).
- Both share one `concurrency` group so they never race on the database.

Credentials come from **GitHub Secrets** (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`,
optional `EBAY_APP_TOKEN`). Both workflows are pinned to `ubuntu-22.04` because
`playwright install --with-deps` fails on Ubuntu 24.04 (`libasound2`).

## Tests

```bash
python -m pytest tests/ -q
```

The selectors used for scraping are best-effort and **will drift** as the target
sites change their markup; treat the provider/benchmark modules as maintained
templates rather than guaranteed-stable integrations.
