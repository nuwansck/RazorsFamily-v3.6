# CPR Gold Bot — v3.3

Automated XAU/USD trading bot built on a Central Pivot Range (CPR) breakout
strategy. Runs every N minutes (default 5), applies layered execution guards,
places orders through the OANDA REST API, and reports every decision to
Telegram.

---

## Table of contents

1. [Architecture overview](#1-architecture-overview)
2. [Project structure](#2-project-structure)
3. [Strategy design](#3-strategy-design)
4. [Signal scoring model](#4-signal-scoring-model)
5. [Position sizing](#5-position-sizing)
6. [Stop loss and take profit](#6-stop-loss-and-take-profit)
7. [Execution guard pipeline](#7-execution-guard-pipeline)
8. [Margin management](#8-margin-management)
9. [Risk controls](#9-risk-controls)
10. [News filter](#10-news-filter)
11. [Trading sessions](#11-trading-sessions)
12. [Break-even logic](#12-break-even-logic)
13. [State management and reconciliation](#13-state-management-and-reconciliation)
14. [Database and observability](#14-database-and-observability)
15. [Configuration reference](#15-configuration-reference)
16. [Secrets and environment variables](#16-secrets-and-environment-variables)
17. [Deployment (Railway)](#17-deployment-railway)
18. [Running locally](#18-running-locally)
19. [Performance analysis tool](#19-performance-analysis-tool)
20. [Changelog](#20-changelog)

---

## 1. Architecture overview

```
scheduler.py          <- APScheduler: fires run_bot_cycle() every N min
    └── bot.py        <- Main cycle orchestrator
          ├── signals.py            <- CPR scoring engine (reads OANDA candles)
          ├── oanda_trader.py       <- OANDA REST API layer
          ├── news_filter.py        <- Economic calendar guard
          ├── calendar_fetcher.py   <- Forex Factory calendar sync
          ├── reconcile_state.py    <- Broker-state reconciliation
          ├── database.py           <- SQLite observability store
          ├── telegram_alert.py     <- Telegram sender
          └── telegram_templates.py <- All message strings
```

Key design decisions:

- **Broker is source of truth.** On every cycle `reconcile_state` checks open
  trades at OANDA and recovers any missing from local history.
- **Atomic file writes.** All JSON state files are written via a temp-file
  rename to prevent corruption on crash.
- **One concurrent position.** `max_concurrent_trades = 1` by default.
- **No TA-Lib.** Signal generation uses only the OANDA candles API and
  pure Python math.

---

## 2. Project structure

```
GOLD v2.0/
├── bot.py                  # Main cycle orchestrator
├── scheduler.py            # APScheduler entry point
├── signals.py              # CPR signal engine
├── oanda_trader.py         # OANDA execution layer
├── news_filter.py          # News block / penalty logic
├── calendar_fetcher.py     # Forex Factory calendar sync
├── reconcile_state.py      # Broker <-> local state reconciliation
├── database.py             # SQLite persistence (observability)
├── state_utils.py          # JSON file helpers, path constants
├── config_loader.py        # Settings + secrets loader
├── telegram_alert.py       # Telegram HTTP sender
├── telegram_templates.py   # All Telegram message templates
├── logging_utils.py        # Structured logging + secret redaction
├── startup_checks.py       # Config validation on startup
├── bootstrap_settings.py   # One-shot settings bootstrapper (optional)
├── analyze_trades.py       # CLI performance dashboard
├── settings.json           # Default config (copied to /data on first run)
├── Procfile                # Railway process definition
├── railway.json            # Railway deployment config
└── requirements.txt        # Python dependencies
```

Runtime data (written to `DATA_DIR`, default `/data`):

```
/data/
├── settings.json                # Live settings (editable at runtime)
├── trade_history.json           # Active trade records (rolling 90 days)
├── signal_cache.json            # Signal dedup cache (score + direction)
├── ops_state.json               # Operational alert dedup cache
├── runtime_state.json           # Cycle state + cooldown + calendar state
├── calendar_cache.json          # Parsed news events (Forex Factory)
├── cpr_gold.db                  # SQLite observability database
└── logs/
    └── cpr_gold_bot.log         # Rotating log (5 x 1 MB)
```

> `cpr_cache.json` was removed in v2.5 — CPR levels are now always fetched live from OANDA.

---

## 3. Strategy design

### 3.1 Central Pivot Range (CPR)

Calculated from the **previous day's** OHLC:

| Level | Formula |
|-------|---------|
| Pivot | (H + L + C) / 3 |
| BC (Bottom Central) | (H + L) / 2 |
| TC (Top Central) | (Pivot - BC) + Pivot |
| R1 | (2 x Pivot) - L |
| R2 | Pivot + (H - L) |
| S1 | (2 x Pivot) - H |
| S2 | Pivot - (H - L) |

Market bias:

- Price **above TC** -> bullish bias -> look for BUY
- Price **below BC** -> bearish bias -> look for SELL
- Price **inside CPR** -> no trade zone

### 3.2 Breakout conditions

| Condition | Score | Setup label |
|-----------|------:|-------------|
| Price > R2 | +1 | R2 Extended Breakout |
| TC < Price <= R2, Price > R1 | +2 | R1 Breakout |
| TC < Price <= R1, Price > PDH | +2 | PDH Breakout |
| Price > TC (other) | +2 | CPR Bull Breakout |
| Price < S2 | +1 | S2 Extended Breakdown |
| S2 <= Price < BC, Price < S1 | +2 | S1 Breakdown |
| S2 <= Price < S1, Price < PDL | +2 | PDL Breakdown |
| Price < BC (other) | +2 | CPR Bear Breakdown |

### 3.3 SMA alignment (M15, last 50 completed candles)

| Condition | Score |
|-----------|------:|
| Both SMA20 and SMA50 confirm direction | +2 |
| One SMA confirms direction | +1 |
| Neither SMA confirms | +0 |

### 3.4 CPR width filter

`CPR width % = abs(TC - BC) / Pivot x 100`

| Width | Interpretation | Score |
|-------|---------------|------:|
| < 0.5% | Narrow — breakout likely | +2 |
| 0.5%–1.0% | Moderate | +1 |
| > 1.0% | Wide — range-bound | +0 |

---

## 4. Signal scoring model

| Component | Max score |
|-----------|----------:|
| Breakout strength | 2 |
| SMA alignment | 2 |
| CPR width | 2 |
| **Total** | **6** |

Minimum score to trade: **4**

Every Telegram signal alert shows three check panels:

- **Mandatory** — score >= 3, RR >= 2
- **Quality** — TP distance >= 0.5%
- **Execution** — session, news, cooldown, open trade, spread, margin

Decision label: `WATCHING` | `BLOCKED` | `READY`

---

## 5. Position sizing

Score-to-risk mapping (dollar amounts read from `settings.json`):

| Score | Risk | Default |
|-------|------|---------|
| 5–6 | `position_full_usd` | $100 |
| 3–4 | `position_partial_usd` | $66 |
| 0–2 | No trade | $0 |

Units calculation:

```
units = position_risk_usd / sl_usd
```

Example: $66 risk, $6 SL -> 11 units of XAU/USD.

A news soft penalty can reduce the effective score before position size is
determined.

---

## 6. Stop loss and take profit

### SL (priority order)

1. CPR structural level (BC for longs, TC for shorts) — when within 0.25% of entry
2. Fixed percentage fallback — 0.25% of entry

### TP (priority order)

1. R1/S1 level — when between 0.50% and 0.75% from entry
2. Fixed percentage fallback — 0.75% of entry
3. **Trade rejected** — if R1/S1 < 0.50% from entry (insufficient room)

### RR constraint

**Minimum RR of 1:2 is enforced.** Trades with TP/SL ratio < 2.0 are
rejected before order placement.

### Price offsets

| Direction | SL price | TP price |
|-----------|----------|----------|
| BUY | entry - sl_usd | entry + tp_usd |
| SELL | entry + sl_usd | entry - tp_usd |

Gold pip = 0.01

---

## 7. Execution guard pipeline

Guards run in this exact sequence. Failure at any stage skips the trade,
writes a DB record, and sends a Telegram notification.

```
 1. Trading enabled?         settings.enabled + TRADING_DISABLED env var
 2. Market open?             Skip Saturday, Sunday, Monday pre-08:00 SGT
 3. Friday cutoff?           No entries after configured hour (default 23:00 SGT)
 4. Session active?          US 00:00-00:59 / London 16:00-20:59 / US 21:00-23:59 SGT
 5. News hard block?         +-30 min around FOMC, NFP, Powell, Rate Decision...
 6. OANDA login OK?          Balance > 0
 7. Daily loss cap?          max_losing_trades_day (default 3)
 8. Daily trade cap?         max_trades_day (default 8)
 9. Loss cooldown?           2 consecutive losses -> 30 min pause
10. Session loss sub-cap?    Per-session max losses (default 2)
11. Window cap?              London <= 4, US <= 4
11. Concurrent trade cap?    max_concurrent_trades (default 1)
12. Signal score >= 3?       CPR engine evaluation
13. Signal blockers clear?   RR >= 2, TP distance >= 0.5%
14. Margin guard?            Pre-trade size cap; retry at lower factor if needed
15. Spread guard?            Session-specific pip limits
 -> Place order
```

---

## 8. Margin management

### Pre-trade cap

```
effective_rate = max(oanda_live_margin_rate, xau_margin_rate_override)
max_units      = (free_margin x margin_safety_factor) / (entry x effective_rate)
```

### Broker-rejection retry

If OANDA returns `INSUFFICIENT_MARGIN`:

```
retry_units = (free_margin x margin_retry_safety_factor) / (entry x effective_rate)
```

One retry is attempted. If still rejected, trade is skipped and a Telegram
alert is sent with full margin detail.

### Defaults

| Setting | Default |
|---------|---------|
| `xau_margin_rate_override` | 0.20 |
| `margin_safety_factor` | 0.60 |
| `margin_retry_safety_factor` | 0.40 |

---

## 9. Risk controls

| Rule | Default |
|------|---------|
| Max concurrent trades | 1 |
| Max trades per day | 8 |
| Max losing trades per day | 3 |
| Max London-window trades | 4 (`max_trades_london`) |
| Max US-window trades | 4 (`max_trades_us`) |
| Consecutive-loss cooldown | 30 min (triggers after 2 consecutive losses) |
| Friday cutoff | 23:00 SGT |

---

## 10. News filter

### Hard block — major events

Trades fully blocked for +-30 min around events matching:
FOMC, Non-Farm Payrolls, Powell, Rate Decision, Fed Chair, Federal Reserve

### Soft penalty — medium events

Score reduced by 1 when within block window of:
CPI, Core CPI, PCE, Core PCE, Unemployment, Jobless Claims

The penalty may reduce position size or eliminate the trade entirely if score
falls below 3. A Telegram notification is sent when a penalty fires.

### Impact level handling

Both `high` and `medium-high` impact values from the Forex Factory feed are
accepted. The `news_filter` recognises `high`, `3`, `red`, and `medium-high`.

### Calendar refresh

Refreshed at most once per `calendar_fetch_interval_min` (default 60 min).
HTTP 429 triggers a `calendar_retry_after_min` (default 15 min) backoff.
The existing cache is always preserved on fetch failure.

---

## 11. Trading sessions

All times are **Singapore Time (SGT, UTC+8)**.

| Session | Hours (SGT) | Max trades |
|---------|-------------|-----------|
| US (NY continuation) | 00:00–00:59 | 4 (shared `max_trades_us`) |
| Dead zone | 01:00–15:59 | No new entries |
| London | 16:00–20:59 | 4 (`max_trades_london`) |
| US | 21:00–23:59 | 4 (`max_trades_us`) |

During the dead zone, existing trade management (reconciliation,
backfill) continues normally. Break-even SL moves are disabled.

---

## 12. Break-even logic

> **Enabled in v2.7** — `breakeven_enabled` is `true`. After a trade moves
> active. SL is fixed at entry via `pct_based` mode (0.25%) and does not move
> after the trade opens. The setting `breakeven_trigger_usd` ($5) and the
> `breakeven_moved` flag are retained in state records for forward compatibility
> but have no operational effect.

---

## 13. State management and reconciliation

### JSON state files

| File | Purpose |
|------|---------|
| `trade_history.json` | Active trade records (rolling 90 days) |
| `signal_cache.json` | Signal dedup (score/direction) |
| `ops_state.json` | Operational alert dedup (caps, cooldowns, session, news) |
| `runtime_state.json` | Cycle metadata, cooldown state, calendar refresh state |

All writes are atomic (temp file + rename).

### Ops state reconciliation on startup

On every cycle, `_reconcile_ops_state()` runs immediately after loading
`ops_state.json`. It silently pre-seeds missing dedup keys from actual live
state (loss count, active cooldown) so that a brand-new deployment or volume
remount does not re-fire alerts that were already sent before the restart.
No Telegram messages are sent during reconciliation — it is purely a dedup
warm-up.

### Reconciliation

Every cycle after OANDA login:

1. Fetch all open trades at broker
2. Insert any broker-open trade missing from local history (recovery)
3. Back-fill `realized_pnl_usd` on locally-FILLED trades now closed at broker

### Duplicate alert prevention

Both `backfill_pnl` and `reconcile_state` can detect a newly closed trade.
The `closed_alert_sent` field on each trade record ensures `msg_trade_closed`
is sent exactly once.

---

## 14. Database and observability

SQLite at `DATA_DIR/cpr_gold.db` (WAL mode).

| Table | Contents |
|-------|---------|
| `cycle_runs` | Every cycle: start, finish, status, summary JSON |
| `signals_log` | Every signal: pair, score, direction, full payload |
| `trades` | Every order attempt: result, broker ID, note |
| `bot_state` | Key-value runtime state snapshots |

Daily cleanup deletes rows older than `db_retention_days`. Weekly VACUUM
runs on Sundays when `db_vacuum_weekly = true`.

---

## 15. Configuration reference

### Strategy

| Key | Default | Description |
|-----|---------|-------------|
| `signal_threshold` | 4 | Minimum score to trade (v2.4: raised from 3) |
| `position_full_usd` | 100 | Risk in USD for score 5–6 |
| `position_partial_usd` | 66 | Risk in USD for score 3–4 |
| `sl_mode` | `pct_based` | `pct_based` / `fixed_usd` / `atr_based` |
| `tp_mode` | `rr_multiple` | `rr_multiple` / `fixed_usd` |
| `sl_pct` | 0.0025 | SL as % of entry (pct_based mode) |
| `rr_ratio` | 3.0 | R:R multiplier (rr_multiple mode) |
| `fixed_sl_usd` | 12.5 | Fixed SL in USD (fixed_usd mode) |
| `atr_sl_multiplier` | 0.5 | ATR multiplier (atr_based mode) |
| `sl_min_usd` | 4.0 | ATR SL floor |
| `sl_max_usd` | 20.0 | ATR SL ceiling |
| `breakeven_trigger_usd` | 5.0 | Profit move to trigger break-even (**feature disabled** — `breakeven_enabled: false`) |
| `breakeven_enabled` | false | Master switch for break-even SL moves — **disabled, do not enable** without also switching `sl_mode` away from `pct_based` |
| `exhaustion_atr_mult` | 2.0 | Stretch threshold for trend exhaustion penalty (0 = disabled) |

### Risk

| Key | Default | Description |
|-----|---------|-------------|
| `max_concurrent_trades` | 1 | Max simultaneous open positions |
| `max_trades_day` | 8 | Max trades per calendar day |
| `max_losing_trades_day` | 3 | Max losing trades per calendar day |
| `max_trades_london` | 4 | Max trades in London window |
| `max_trades_us` | 4 | Max trades in US window |
| `max_losing_trades_session` | 2 | Max losses per session before it pauses |
| `trading_day_start_hour_sgt` | 8 | Hour (SGT) when daily cap counter resets |
| `loss_streak_cooldown_min` | 30 | Cooldown after 2 consecutive losses |

### Sessions

| Key | Default | Description |
|-----|---------|-------------|
| `session_only` | true | Only trade in active sessions |
| `session_thresholds` | `{London:3,US:3}` | Per-session min score (Asian session disabled) |
| `friday_cutoff_hour_sgt` | 23 | No entries after this hour on Fridays |

### Margin

| Key | Default | Description |
|-----|---------|-------------|
| `margin_safety_factor` | 0.6 | Pre-trade utilisation ceiling |
| `margin_retry_safety_factor` | 0.4 | Retry utilisation ceiling |
| `xau_margin_rate_override` | 0.20 | Conservative gold margin rate floor |
| `auto_scale_on_margin_reject` | true | Retry smaller on broker rejection |

### News

| Key | Default | Description |
|-----|---------|-------------|
| `news_filter_enabled` | true | Enable news filtering |
| `news_block_before_min` | 30 | Block minutes before major event |
| `news_block_after_min` | 30 | Block minutes after major event |
| `news_lookahead_min` | 120 | Lookahead for informational display |
| `calendar_fetch_interval_min` | 60 | Min minutes between refreshes |
| `calendar_retry_after_min` | 15 | Backoff after HTTP 429 |

### Spread

| Key | Default | Description |
|-----|---------|-------------|
| `max_spread_pips` | 150 | Global fallback spread limit |
| `spread_limits` | `{London:130,US:130}` | Per-session limits (Asian session disabled) |

### Infrastructure

| Key | Default | Description |
|-----|---------|-------------|
| `bot_name` | `CPR Gold Bot` | Display name |
| `demo_mode` | true | `true` = practice, `false` = live |
| `trade_gold` | true | Order placement master switch |
| `enabled` | true | Full cycle master switch |
| `cycle_minutes` | 5 | Bot cycle interval |
| `db_retention_days` | 90 | Data rolling retention window |
| `db_vacuum_weekly` | true | SQLite VACUUM on Sundays |

---

## 16. Secrets and environment variables

Environment variables **always take priority** over `secrets.json`. In
production (Railway), set all secrets as environment variables and do not
deploy `secrets.json`.

| Variable | Required | Description |
|----------|----------|-------------|
| `OANDA_API_KEY` | Yes | OANDA v20 API token |
| `OANDA_ACCOUNT_ID` | Yes | OANDA account ID |
| `TELEGRAM_TOKEN` | Yes | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Yes | Telegram chat / group ID |
| `DATA_DIR` | No | Persistent data path (default `/data`) |
| `TRADING_DISABLED` | No | Set `true` to pause trading without restart |
| `LOG_LEVEL` | No | `DEBUG` / `INFO` / `WARNING` (default `INFO`) |

For local development, create `secrets.json` in the project root (it is in
`.gitignore`). Do not commit it.

---

## 17. Deployment (Railway)

```
Procfile:     web: python scheduler.py
railway.json: startCommand: python scheduler.py
```

Required environment variables in Railway dashboard:

```
OANDA_API_KEY
OANDA_ACCOUNT_ID
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
DATA_DIR=/data
```

Mount a Railway volume at `/data` to persist state across deploys.

---

## 18. Running locally

```bash
# Install dependencies
pip install -r requirements.txt

# Set secrets
export OANDA_API_KEY=your_key
export OANDA_ACCOUNT_ID=your_account
export TELEGRAM_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
export DATA_DIR=./data

# Single cycle (dry-run style)
python bot.py

# Full scheduler
python scheduler.py
```

Pause trading without stopping the process:

```bash
export TRADING_DISABLED=true
# or edit DATA_DIR/settings.json: "enabled": false
```

---

## 19. Performance analysis tool

```bash
python analyze_trades.py              # All-time closed trades
python analyze_trades.py --all        # Include failed orders
python analyze_trades.py --last 30    # Last 30 days (SGT-correct)
```

Output sections: overall stats, by session, by setup, by score, monthly P&L
bar chart, and a verdict with recommendations.

---

## 20. Changelog

### v2.7.3 — 2026-03-20

**Per-session total trade caps wired into settings (`max_trades_london`, `max_trades_us`)**

Files changed: `settings.json`, `settings.json.example`, `bot.py`, `config_loader.py`,
`version.py`, `README.md`, `CONFLUENCE_READY.md`

`max_trades_london` and `max_trades_us` were already implemented in `bot.py`
(`get_window_trade_cap()`) but were missing from `settings.json`, falling back
to a hardcoded default of 4. Now explicit in settings with demo values of 10 each.

Both keys added to `_FORCE_SYNC_KEYS` in `config_loader.py` so future deploys
automatically correct stale volume values. Added to `validate_settings()` defaults
and both `setdefault` blocks in `load_settings()`.

| Setting | Value | Meaning |
|---|---|---|
| `max_trades_london` | `10` | Max total trades in London session (16:00–20:59 SGT) |
| `max_trades_us` | `10` | Max total trades in US session (00:00–00:59 + 21:00–23:59 SGT) |

For live: set both to `4–5` to limit overtrading in any single session.

---

### v2.7.2 — 2026-03-20

**Demo optimisation — disable break-even, widen caps, tighten re-entry wait, lower RR**

Files changed: `settings.json.example`, `version.py`, `bot.py`, `README.md`, `CONFLUENCE_READY.md`

**Change 1 — Break-even disabled (`breakeven_enabled: false`)**
Break-even was firing at just 381 pips (11% of the way to TP). Gold routinely
retraces 200–500 pips mid-move, scratching trades at $0 that would have run to
TP. With a 40% WR and 2.75× RR the strategy is profitable without the crutch.

**Change 2 — RR ratio lowered to 2.75× (`rr_ratio: 2.75`)**
TP moves 291 pips closer (3,488 → 3,197 pips avg). $3.83 less per win, but
8.3% easier to hit. Breakeven WR stays comfortable at 26.7% vs current 40%.
EV per trade: +$7.67 (vs +$9.20 at 3×) — still strongly positive.

**Change 3 — Daily and session caps widened for demo**
`max_trades_day: 20` — wins never block new entries, only losses count.
`max_losing_trades_day: 8` — full day stops at 8 losses.
`max_losing_trades_session: 4` — session pauses at 4 losses.
Rationale: demo mode needs maximum data. The loss-streak cooldown (30 min)
and per-session sub-cap still prevent runaway churn.

**Change 4 — Min re-entry wait reduced (`min_reentry_wait_min: 5`)**
Shorter floor between trades for faster data collection in demo.

**Live equivalents when switching to real money:**
```json
"breakeven_enabled": true,
"rr_ratio": 3.0,
"max_trades_day": 8,
"max_losing_trades_day": 4,
"max_losing_trades_session": 2,
"min_reentry_wait_min": 10
```

---

### v2.7.1 — 2026-03-20

**Hotfix — config_loader 999 fallback and volume force-sync**

Files changed: `config_loader.py`, `version.py`, `bot.py`, `settings.json.example`,
`README.md`, `CONFLUENCE_READY.md`

**Root cause:** `config_loader.py` had `setdefault('max_losing_trades_day', 999)`
and `setdefault('max_trades_day', 999)` hardcoded in both
`ensure_persistent_settings()` and `load_settings()`. On first boot these
seeded the Railway volume with unsafe values. On subsequent deploys the stale
volume values (999) were never overwritten because `setdefault` only fills
missing keys — so the Telegram startup message showed `Max losses/day: 999`
even after the settings.json was corrected.

**Fix 1 — Hardcoded 999 fallbacks replaced** with correct safe defaults:
`max_trades_day: 8`, `max_losing_trades_day: 3`, plus added missing keys
`max_losing_trades_session: 2`, `loss_streak_cooldown_min: 30`,
`min_reentry_wait_min: 10`, `breakeven_enabled: True`, `signal_threshold: 4`.

**Fix 2 — Force-sync for 7 safety-critical keys** added to
`ensure_persistent_settings()`. On every deploy these keys are compared
against the bundled `settings.json` defaults and overwritten if they differ —
same mechanism already used for `bot_name`. The 7 keys:
`max_losing_trades_day`, `max_losing_trades_session`, `max_trades_day`,
`loss_streak_cooldown_min`, `min_reentry_wait_min`, `breakeven_enabled`,
`signal_threshold`.

**Effect:** On the next Railway deploy the volume's stale 999 values are
automatically corrected to 3/2/8/30/10/true/4 without any manual volume edits.

---

### v2.7 — 2026-03-20

**Safety guards + Telegram accuracy + docstring corrections**

Files changed: `bot.py`, `telegram_templates.py`, `scheduler.py`, `version.py`,
`settings.json`, `settings.json.example`, `README.md`, `CONFLUENCE_READY.md`

**Fix 1 — Dead-zone second-line guard (`bot.py` — `_execution_phase`)**

Added `is_dead_zone_time(now_sgt)` check as the very first statement in
`_execution_phase()`, before any order is placed. Belt-and-suspenders against
startup reconcile edge cases or a 00:59→01:00 boundary race slipping past the
primary guard in `_guard_phase()`. Logs at WARNING level with event code
`DEAD_ZONE_SKIP` if triggered.

**Fix 2 — Minimum inter-trade wait (`bot.py`)**

New `min_reentry_blocked_until(history, today_str, now_sgt, settings)` helper
enforces a floor pause between any two consecutive trades, independent of the
loss-streak cooldown. Default: 10 minutes (`min_reentry_wait_min: 10`).
Wired into `_guard_phase()` after the cooldown block. Sends a single Telegram
notification per block window via `send_once_per_state()` and logs
`[REENTRY_WAIT]`. Set to 0 to disable.

**Fix 3 — Startup Telegram "Caps: off" corrected (`telegram_templates.py`, `scheduler.py`)**

`msg_startup()` was hardcoded to print `Caps: off` regardless of live settings.
The function now accepts `max_losing_trades_day`, `max_losing_trades_session`,
`loss_streak_cooldown_min`, `min_reentry_wait_min`, and `breakeven_enabled` as
parameters and displays their actual values. The `scheduler.py` call passes all
five from the live settings dict.

**Fix 4 — Version string double-stamp removed (`version.py`, `scheduler.py`)**

`BOT_NAME` was `"CPR Gold Bot v2.6"` and `scheduler.py` composed
`f"{BOT_NAME} v{__version__}"` → `"CPR Gold Bot v2.6 v2.6"` in the startup
Telegram. Fixed by stripping the version suffix from `BOT_NAME`. The composed
string now correctly reads `"CPR Gold Bot v2.7"`.

**Fix 5 — `settings.json.example` restored, `settings.json` removed from package**

`settings.json.example` was missing from the v2.6 package entirely. Restored
with all v2.7 production-safe defaults. `settings.json` (live config) removed
from the archive — it must never ship in the zip. The `.gitignore` already
excludes it; the export process now uses Python `zipfile` to honour that
exclusion.

**Fix 6 — Stale docstring and README breakeven/score references corrected**

`bot.py` line 5 said `breakeven_enabled: false` — now `true`. Line 12 said
`score < 3 → no trade` — corrected to `score < 4 (MIN_TRADE_SCORE = 4)`.
README section 12 breakeven note updated to reflect enabled state.

---

### v2.6 — 2026-03-19

**All trading caps removed + config hardening**

Files changed: `settings.json`, `config_loader.py`, `telegram_templates.py`,
`scheduler.py`, `version.py`, `README.md`, `CONFLUENCE_READY.md`

**Change 1 — All caps set to off (`settings.json`)**

`max_losing_trades_day`, `max_trades_day`, `max_losing_trades_session`,
`max_trades_london`, `max_trades_us` all set to `999` (effectively off).
`loss_streak_cooldown_min` set to `0` (disabled). Friday cutoff kept.

**Change 2 — Hardcoded fallback defaults fixed (`config_loader.py`)**

`setdefault` calls in both `ensure_persistent_settings()` and `load_settings()`
were hardcoded to `max_trades_day=8` and `max_losing_trades_day=3`. On a
fresh volume these values would override `settings.json`, causing the old caps
to reappear after every new deployment. Fixed to use `999`.

**Change 3 — Cap references removed from Telegram messages (`telegram_templates.py`, `scheduler.py`)**

Startup message no longer shows per-session cap numbers or daily loss cap.
Session open message no longer shows window trade cap. Replaced with
`Caps: off` in startup message.

---

### v2.5 — 2026-03-19

**Bug-fix release — 5 fixes**

Files changed: `bot.py`, `signals.py`, `oanda_trader.py`, `version.py`,
`settings.json`, `settings.json.example`, `README.md`, `CONFLUENCE_READY.md`

**Fix 1 — Duplicate Cooldown + Daily Cap Telegram alerts within a running session (`bot.py`)**

After the daily loss cap was hit, the 🧊 Cooldown Started and 🛑 Daily Cap
Reached messages were sent again on every subsequent 5-minute cycle.

Root cause (a): `trigger_marker` in `maybe_start_loss_cooldown()` was built
from trade fields only, with no date prefix — if history ordering shifted after
a `backfill_pnl` write the marker changed, bypassing the dedup check and
generating a new cooldown entry each cycle.  Fixed by prefixing with `today_str`.

Root cause (b): Both loss-cap return paths called `ops.pop("cooldown_started_state")`
which wiped the dedup key, allowing the Cooldown alert to re-fire on the very
next cycle.  Fixed by removing both `pop` calls — the `_reconcile_ops_state`
warm-up (Fix 4) renders them unnecessary.

**Fix 2 — CPR TC/BC inversion causes infinite cache-discard loop (`signals.py`)**

`_validate_cpr_levels()` hard-rejected any cache where TC < BC and triggered a
re-fetch — but re-fetching from OANDA returned identical data, repeating the
warning every 5 minutes.  TC < BC is a valid edge case when `prev_close <
avg(H, L)` (i.e. `pivot < bc`).  Fixed by normalising in-place: when TC < BC
the function now swaps TC ↔ BC and continues validation rather than discarding.
One `WARNING` is logged on the first occurrence; subsequent cycles are silent.

**Fix 3 — SL/TP prices anchored to signal price, not actual fill price
(`oanda_trader.py`, `bot.py`)**

`place_order()` computes SL/TP from the live bid/ask at execution time but did
not return those values.  `bot.py` recomputed SL/TP from the signal entry price
instead — after slippage (10–14 pips observed) the broker's actual SL/TP and
the logged/Telegram values diverged.  Fixed by returning `sl_price` and
`tp_price` from `place_order()` and using those broker-confirmed values in the
trade record, falling back to recomputing from `fill_price` only if not supplied.

**Fix 4 — Duplicate alerts re-fire after every fresh deployment (`bot.py`)**

On a brand-new deployment `ops_state.json` starts empty. All dedup keys are
blank so `send_once_per_state()` fires every alert again — even if the daily
cap was already hit or a cooldown was already active before the restart.

Fixed by adding `_reconcile_ops_state()`, called at the top of every cycle
immediately after loading `ops_state.json`. It checks actual live state
(loss count from history, active cooldown from `runtime_state.json`) and
silently pre-seeds the missing dedup keys before any alert can run.
No Telegram messages are sent — it is a pure warm-up. This makes the dedup
system deployment-proof.

**Fix 5 — CPR levels cached on Railway volume causing stale data (`signals.py`)**

`cpr_cache.json` persisted across deployments on the Railway `/data` volume.
After a mid-day redeploy the bot could run with yesterday's CPR levels for the
rest of the session, producing wrong signals.

Fixed by removing the cache entirely. CPR levels are now always fetched live
from OANDA's daily candles endpoint on every cycle. `_validate_cpr_levels()`
still runs on the freshly computed levels to catch structural edge cases.
`cpr_cache.json` on the volume can be safely deleted — it is no longer read
or written.

---

### v2.4 — 2026-03-19
**Features: 08:00 SGT trading-day boundary + per-session loss sub-cap + signal threshold 4 + trend exhaustion penalty**

Four improvements from the v3.x feature track backported into the v2.x lineage.

---

#### 1. 08:00 SGT trading-day boundary (replaces calendar midnight)

The trading day now resets at **08:00 SGT** instead of calendar midnight (`00:00`).
Any time before 08:00 SGT (e.g. 01:00–07:59) belongs to the *previous* day's cap bucket.
This prevents overnight US losses from counting against the incoming London session's day cap.

New helper: `get_trading_day(now_sgt, day_start_hour=8)` — used everywhere `today` is computed.

**New setting:**
| Key | Default | Description |
|---|---|---|
| `trading_day_start_hour_sgt` | `8` | Hour (SGT) at which the cap counter resets |

---

#### 2. Per-session loss sub-cap (2 losses per session)

Each session (London / US) gets its own 2-loss limit. When a session hits its sub-cap it pauses
while the daily 3-loss hard stop still accumulates across sessions.

| Scenario | Session | Day cap | Bot behaviour |
|---|---|---|---|
| 2 losses in London | Paused | 2/3 used | US can still trade |
| 2 losses in US | Paused | 2/3 used | Next day's London can still trade |
| 3rd loss in US | — | 3/3 hit | Full day stop |

New Telegram alert: `msg_session_cap()` — shows session losses, remaining day losses, and next session.

**New setting:**
| Key | Default | Description |
|---|---|---|
| `max_losing_trades_session` | `2` | Max losses per session before it pauses |

---

#### 3. Signal threshold raised from 3 to 4

Score 3 entries (CPR breakout confirmed but weak SMA alignment or wide CPR) were net negative
in live data — every score-3 trade observed on 2026-03-18 resulted in a loss.

**Also fixed:** `signal_threshold` was stored in `ctx` but never compared against score in previous
versions. Explicit threshold gate added in `_signal_phase()`.

| | v2.3 | v2.4 |
|---|---|---|
| `signal_threshold` | 3 | **4** |
| Score 3 entries | Partial ($66) | **Blocked** |
| Score 4+ entries | Unchanged | Unchanged |

---

#### 4. Trend exhaustion penalty (−1 score when overextended)

If price is more than `exhaustion_atr_mult` × ATR(14) away from SMA20, the score is reduced by 1.
Prevents chasing moves in their late/extended phase.

| Before | After |
|---|---|
| Score 4 at 2.5× stretch → entry placed | Score 4 − 1 = 3 → **blocked** (below threshold 4) |
| Score 5 at 2.5× stretch → entry placed | Score 5 − 1 = 4 → **partial** (downsized) |
| Score 6 at 1.8× stretch → entry placed | Score 6 − 0 = 6 → **full** (under threshold, no penalty) |

**New setting:**
| Key | Default | Description |
|---|---|---|
| `exhaustion_atr_mult` | `2.0` | ATR stretch threshold. Lower = stricter. 0 = disabled. |

---

#### 5. Daily report moved to 15:30 SGT

Daily performance report now fires at **15:30 SGT** (30 min before London open), replacing the
previous 09:30 SGT time. Report arrives just before trading begins.

---

#### 6. Alert improvements

- **`msg_daily_cap()`** — now shows trading window (`16:00 → 01:00 SGT`) and exact reset timestamp
- **`msg_cooldown_started()`** — now shows current session name and remaining day losses
- **`msg_startup()`** — now shows `Window: 16:00 → 01:00 SGT` and `Day reset: 08:00 SGT`
- **`msg_new_day_resume()`** — now shows `Day reset: 08:00 SGT`
- **`msg_session_cap()`** — new alert for per-session sub-cap

---

**Files changed:** `bot.py`, `signals.py`, `scheduler.py`, `telegram_templates.py`,
`settings.json`, `settings.json.example`, `version.py`, `README.md`, `CONFLUENCE_READY.md`

---

### v2.2 — 2026-03-18
**Technical fixes: 7 bugs backported from v3.5 — no strategy changes**

All fixes are pure technical/operational improvements. CPR strategy, signal
scoring, session windows, SL/TP logic, and all trading behaviour are unchanged.

---

**Fix 1 — `version.py` / `settings.json`: version string correct on every deploy**

`version.py` bumped to `"2.2"`. `settings.json` `bot_name` set to
`"CPR Gold Bot v2.2"`. The startup Telegram and scheduler banner now correctly
reflect the deployed version.

---

**Fix 2 — `config_loader.py`: `bot_name` auto-syncs on redeploy**

`ensure_persistent_settings()` previously only injected *missing* keys into the
persistent volume file. `bot_name` — an existing key — was never updated. After
any redeploy the displayed version stayed at whatever was written on first boot.

Fix: `bot_name` is now always synced from the bundled `settings.json` when it
differs from the volume copy. All other user-editable settings remain untouched.

---

**Fix 3 — `bot.py` `daily_totals()`: loss cap overshoots to 4/3**

`daily_totals()` counted closed losses from history but not the open position's
current unrealized P&L. When 3 losses hit the cap, an already-open losing trade
closed one cycle later — `backfill_pnl()` recorded it — producing a 4/3 display.

Fix: when `trader` is supplied, if `unrealized < 0` the loss counter is
incremented immediately, so the cap fires before the trade closes.

---

**Fix 4 — `bot.py` `send_once_per_state()`: shared key collision causing repeated alerts**

All operational alert types shared a single `"ops_state"` key. When two
conditions were active simultaneously, each write overwrote the other's key value,
causing the other to re-fire every 5 minutes indefinitely.

Fix: each alert type now has its own dedicated key:
`loss_cap_state`, `trade_cap_state`, `cooldown_started_state`,
`cooldown_guard_state`, `window_cap_state`, `open_cap_state`, `spread_state`.

---

**Fix 5 — `bot.py` `_guard_phase()`: loss cap / cooldown message ordering**

The `cooldown_started` notification (showing "Resumes HH:MM SGT") ran before
the daily loss cap check. When the cap was hit, the bot sent "Resumes HH:MM"
then immediately "Bot resumes next trading day" — two contradicting messages.

Fix: an early loss cap check now runs before the cooldown notification. When
the cap is hit the bot returns immediately with the correct message only.

---

**Fix 6 — `signals.py`: CPR cache validation**

Cached CPR levels were trusted without any integrity check. Corrupted or
structurally impossible values (e.g. TC < BC) would be used silently.

Fix: `_validate_cpr_levels()` runs 8 structural checks on every cache hit.
On failure the cache is discarded and levels are re-fetched from OANDA.
Fresh fetches now log at INFO level (previously debug-only) so levels are
always visible in Railway logs for cross-checking against your chart.

---

**Fix 7 — Startup OANDA reconciliation (loss cap deployment-proof)**

After a mid-day redeploy `history.json` may be missing trades that closed
between the last save and the restart. `daily_totals()` under-counts losses
and the loss cap fails to fire.

Fix: on every process start, `startup_oanda_reconcile()` fetches today's
closing ORDER_FILLs from OANDA's transactions endpoint and injects any
missing records into history before the first cycle runs.
A Telegram alert lists any injected trade IDs.

New method: `OandaTrader.get_today_closed_transactions()`
New function: `startup_oanda_reconcile()` in `reconcile_state.py`

---

**Fix 8 — Reports: profit factor, best trade, worst trade added to daily report**

Daily Telegram report now shows:
```
  P.Factor: 2.97
  Best:     +$123.76  (21:15 SGT)
  Worst:    -$53.77   (21:21 SGT)
```
Weekly and monthly reports also show best/worst trade after the Streaks line.
`_stats()` in `reporting.py` extended with `best_trade` and `worst_trade`.

---

**Files changed:** `version.py`, `settings.json`, `config_loader.py`, `bot.py`,
`signals.py`, `oanda_trader.py`, `reconcile_state.py`, `reporting.py`,
`telegram_templates.py`, `telegram_alert.py`, `README.md`, `CONFLUENCE_READY.md`

---

### v2.1 — 2026-03-18
**Bug fix — TP fallback when R1/S1 is too close**

| | Detail |
|---|---|
| **File** | `signals.py` |
| **Problem** | When R1/S1 structural level was < 0.50% from entry, the trade was hard-blocked even on a perfect 6/6 signal score |
| **Root cause** | TP selection logic treated R1/S1 < 0.50% as a skip condition instead of falling back to the configured fixed TP |
| **Fix** | R1/S1 < 0.50% now falls back to fixed 0.75% TP (`fixed_pct_fallback`), preserving the intended 1:3 R:R and allowing valid signals to fire |
| **Impact** | Trades with perfect setups that were previously blocked by tight structural levels will now execute correctly |

---

### v2.0 — 2026-03-18
**Production release — fixed SL mode + breakeven mover disabled**

| | Detail |
|---|---|
| **Files** | `bot.py`, `settings.json`, `config_loader.py` |
| **Change 1** | `sl_mode` set to `pct_based` (0.25% SL / 0.75% TP) — clean fixed percentage, no ATR dependency |
| **Change 2** | `check_breakeven()` disabled — SL never moves after trade open |
| **Change 3** | `config_loader.py` hardened — all required settings keys now injected as defaults in `load_settings()` to prevent crash on stale Railway volume files |
| **RR Ratio** | 1:3 maintained across all trade sizes |

---

### v1.2 — 2026-03-18
**Hotfix — settings validation crash on Railway volume**

| | Detail |
|---|---|
| **File** | `config_loader.py` |
| **Problem** | Bot crashed on startup with `Missing required settings keys` when Railway persistent volume had a stale `settings.json` |
| **Fix** | Required keys merged from bundled `settings.json` defaults during `ensure_persistent_settings()` |

---

### v1.0 — v1.1
**Initial release — CPR breakout strategy on XAU/USD via OANDA**
- CPR signal engine with 6-point scoring model
- Session-aware trading (London / US only — Asian disabled due to insufficient XAU/USD volatility)
- News filter via Forex Factory calendar
- Telegram reporting with daily / weekly / monthly summaries
- Railway deployment with persistent volume state
