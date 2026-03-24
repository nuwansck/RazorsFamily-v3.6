# GOLD v3.3 — Three Production Fixes

**Date:** 2026-03-20
**Version:** v3.0
**Status:** Critical fixes — score threshold, margin rate, position sizing

---

## 1. Fix: Trades firing at score 3 (session_thresholds conflict)

**Problem:** `session_thresholds: {"London": 3}` overrode `signal_threshold: 4`.
Score 3 trades were placed with `score_ok: False` in mandatory checks.

**Fix:** `session_thresholds: {"London": 4, "US": 4}`

---

## 2. Fix: Margin guard cutting 5.6 → 1.4 units (wrong margin rate)

**Problem:** `xau_margin_rate_override: 0.05` — but OANDA demo charges 20% margin.
`apply_margin_guard()` uses `max(oanda_rate, configured_floor)` so the 20% OANDA
rate always won. Max units = $2,282 × 0.6 / ($4,655 × 0.20) = 1.47 units.

**Fix:** `xau_margin_rate_override: 0.20` — now accurate, no more false warnings.

---

## 3. Fix: Position sizes aligned with 20% margin

**Problem:** `position_full_usd: 100` → ~8.6 units requested → always cut to 1.4.
Every trade fired the margin guard warning.

**Fix:** `position_full_usd: 15`, `position_partial_usd: 10`
- Score 4:   10 / $11.67 = ~0.86 units → margin $797 ✅ within $1,369 limit
- Score 5-6: 15 / $11.67 = ~1.29 units → margin $1,196 ✅ within $1,369 limit

No more margin guard adjustments on normal trades.

---

## 4. Full settings snapshot (v3.0)

| Key | v2.9 | v3.0 | Reason |
|---|---|---|---|
| `session_thresholds` | `{London:3, US:3}` | `{London:4, US:4}` | Match signal_threshold |
| `xau_margin_rate_override` | `0.05` | `0.20` | Match OANDA demo rate |
| `position_full_usd` | `100` | `15` | Align with margin reality |
| `position_partial_usd` | `66` | `10` | Align with margin reality |

---

## 5. Files changed

| File | Change |
|---|---|
| `settings.json` + `settings.json.example` | All 4 values corrected |
| `config_loader.py` | 4 new keys in `_FORCE_SYNC_KEYS`; setdefaults updated |
| `signals.py` | Reads sl/tp pct from settings (v2.9 fix carried forward) |
| `telegram_templates.py` | R:R display `.2f` |
| `version.py` | `3.0` |
| `bot.py` | Docstring → v3.0 |
| `README.md` + `CONFLUENCE_READY.md` | Updated |

---

## 6. Upgrade checklist

1. Deploy v3.0
2. Logs: `Updated N key(s): ['session_thresholds', 'xau_margin_rate_override', ...]`
3. No more margin guard warnings on normal trades
4. Signals: only score 4+ fire trades
5. Startup Telegram: sizes now `$10 (score 4) | $15 (score 5–6)`

---

# GOLD v2.8 — RR Ratio 2.65×

**Date:** 2026-03-20
**Version:** v2.8
**Status:** Demo — RR fine-tuning

---

## 1. Change

`rr_ratio` adjusted from `2.75` to `2.65`. TP moves ~116 pips closer on average
(3,197 → ~3,081 pips). Marginally easier to hit while still maintaining strong
positive expectancy at 40% win rate.

| Metric | 2.75× | 2.65× |
|---|---|---|
| Avg TP distance | 3,197 pips | ~3,081 pips |
| Avg win (1.4 units) | $42.17 | $40.65 |
| EV @ 40% WR | +$7.67/trade | +$7.36/trade |
| Breakeven WR | 26.7% | 27.4% |

All other v2.7.4 demo settings unchanged.

---

## 2. Files changed

| File | Change |
|---|---|
| `settings.json` | `rr_ratio: 2.65` |
| `settings.json.example` | `rr_ratio: 2.65` |
| `config_loader.py` | `rr_ratio` default updated to `2.65` |
| `version.py` | `__version__` → `"2.8"` |
| `bot.py` | Docstring → v2.8 |
| `README.md` | Header → v2.8; v2.8 changelog added |
| `CONFLUENCE_READY.md` | This section prepended |

---

## 3. Upgrade checklist

1. Deploy v2.8
2. Check Railway logs for `Updated 1 key(s): ['rr_ratio']`
3. Confirm startup Telegram still shows all correct demo caps

---


**Date:** 2026-03-20
**Version:** v2.7.3
**Status:** Settings wiring — no logic changes

---

## 1. Change

`max_trades_london` and `max_trades_us` were already fully implemented in
`bot.py` via `get_window_trade_cap()` but were absent from `settings.json`.
The code fell back to a hardcoded default of 4, making the setting invisible
and un-configurable without a code change.

### Now explicit in settings

| Setting | Demo value | Live recommendation |
|---|---|---|
| `max_trades_london` | `10` | `4–5` |
| `max_trades_us` | `10` | `4–5` |

Both keys added to `_FORCE_SYNC_KEYS` — corrected automatically on next deploy.

---

## 2. Files changed

| File | Change |
|---|---|
| `settings.json` | `max_trades_london: 10`, `max_trades_us: 10` added |
| `settings.json.example` | Same |
| `bot.py` | `setdefault` added to `validate_settings()` |
| `config_loader.py` | Both keys added to `_FORCE_SYNC_KEYS` and both `setdefault` blocks |
| `version.py` | `__version__` → `"2.7.3"` |
| `README.md` | v2.7.3 changelog added |
| `CONFLUENCE_READY.md` | This section prepended |

---

## 3. Upgrade checklist

1. Deploy v2.7.3
2. Check Railway logs for `Updated N key(s): ['max_trades_london', 'max_trades_us']`
3. No other changes — all v2.7.2 demo settings carried forward

---

# GOLD v2.7.2 — Demo Optimisation Release

**Date:** 2026-03-20
**Version:** v2.7.2
**Status:** Demo mode — maximum data collection configuration

---

## 1. Purpose

Four targeted changes to optimise the bot for demo trading. Goal is maximum
trade throughput and data collection while keeping execution discipline intact.
No changes to signal scoring, session windows, or core architecture.

---

## 2. Changes

### 2.1 — Break-even disabled (`breakeven_enabled: false`)

**Problem:** Break-even was firing at ~381 pips — only 11% of the way to TP
(3,488 pips avg). Gold routinely retraces 200–500 pips mid-move, scratching
trades at $0 that would have eventually hit TP.

**Analysis (2026-03-19 data):**
- Break-even confirmed firing on trade 586 at $4588 entry $4593 — SL moved,
  trade scratched at $0 instead of running to TP
- At 1.3–1.4 units, $5 trigger = ~357–385 pip move required
- After trigger fires, 3,114 more pips needed to hit TP

**Decision:** With 40% WR and 2.75× RR, breakeven WR = 26.7%. The strategy
is profitable without break-even. Disabled for demo to let winners run.

### 2.2 — RR ratio lowered to 2.75× (`rr_ratio: 2.75`)

| Metric | 3.0× | 2.75× | Change |
|---|---|---|---|
| TP distance (avg) | 3,488 pips | 3,197 pips | −291 pips (8.3% closer) |
| Avg win | $46.00 | $42.17 | −$3.83 |
| EV @ 40% WR | +$9.20/trade | +$7.67/trade | −$1.53 |
| Breakeven WR | 25.0% | 26.7% | +1.7pp |
| Cushion @ 40% | 15.0pp | 13.3pp | −1.7pp |

Trade-off: slightly lower EV per trade, but TP hits more often. For demo,
more completed trades = better data. Both RR values are strongly profitable.

### 2.3 — Caps widened for demo data collection

| Setting | Before | After | Rationale |
|---|---|---|---|
| `max_trades_day` | 8 | 20 | Wins never block — only losses stop the bot |
| `max_losing_trades_day` | 3 | 8 | More loss tolerance for data collection |
| `max_losing_trades_session` | 2 | 4 | 4 losses per session before pausing |

Guards that remain unchanged: `loss_streak_cooldown_min: 30` still pauses
after 2 consecutive losses. `max_concurrent_trades: 1` still enforces one
trade at a time. `signal_threshold: 4` still filters low-quality setups.

### 2.4 — Min re-entry wait reduced (`min_reentry_wait_min: 5`)

Reduced from 10 to 5 minutes for faster data collection in demo. Still
prevents the rapid churn pattern (2–3 min re-entries) that caused 4
consecutive losses in 20 minutes on 2026-03-19.

---

## 3. Full settings snapshot (v2.7.2 demo)

```json
"breakeven_enabled": false,
"rr_ratio": 2.75,
"max_trades_day": 20,
"max_losing_trades_day": 8,
"max_losing_trades_session": 4,
"loss_streak_cooldown_min": 30,
"min_reentry_wait_min": 5,
"max_concurrent_trades": 1,
"signal_threshold": 4,
"sl_pct": 0.0025,
"sl_mode": "pct_based",
"tp_mode": "rr_multiple"
```

## 4. Live equivalents (when switching to real money)

```json
"breakeven_enabled": true,
"rr_ratio": 3.0,
"max_trades_day": 8,
"max_losing_trades_day": 4,
"max_losing_trades_session": 2,
"min_reentry_wait_min": 10
```

---

## 5. Files changed

| File | Change |
|---|---|
| `settings.json.example` | All 4 setting changes applied |
| `version.py` | `__version__` → `"2.7.2"` |
| `bot.py` | Docstring updated to v2.7.2 |
| `README.md` | Header → v2.7.2; v2.7.2 changelog added |
| `CONFLUENCE_READY.md` | v2.7.2 release notes prepended |

---

## 6. Upgrade checklist

1. Deploy v2.7.2 zip (Railway redeploy)
2. Confirm startup Telegram shows `CPR Gold Bot v2.7.2`
3. Confirm caps in startup message: `Max losses/day: 8`, `Max losses/session: 4`
4. Confirm `Break-even: off`
5. No volume file edits needed — `config_loader` force-sync updates automatically

---

# GOLD v2.7.1 — Hotfix Release Notes

**Date:** 2026-03-20
**Version:** v2.7.1
**Status:** Hotfix — config_loader 999 fallback + volume force-sync

---

## 1. Problem

After deploying v2.7, the startup Telegram showed:

```
Caps:
  Max losses/day:     999
  Max losses/session: 2
  Loss cooldown:      30 min
  Min re-entry wait:  10 min
  Break-even:         on
```

`Max losses/day: 999` despite `settings.json` on the Railway volume having
`max_losing_trades_day: 3`.

---

## 2. Root cause

`config_loader.py` contained two separate occurrences of:

```python
settings.setdefault('max_losing_trades_day', 999)
settings.setdefault('max_trades_day', 999)
```

One in `ensure_persistent_settings()` (first-boot path) and one in
`load_settings()` (every-cycle path). These are `setdefault` calls — they only
fire when the key is **absent**. On the Railway volume, `max_losing_trades_day`
was already present with value `999` from the old v2.6 "caps off" deployment.
`setdefault` therefore never changed it.

`ensure_persistent_settings()` also only merges **missing** keys from the
bundled defaults into the volume file — it does not overwrite existing values
(except for `bot_name`). So even after the bundled `settings.json` was
corrected to `max_losing_trades_day: 3`, the volume retained 999 indefinitely.

---

## 3. Fix

### 3.1 — Hardcoded 999 fallbacks replaced

Both `setdefault` blocks now use correct safe production values:

| Key | Before | After |
|---|---|---|
| `max_trades_day` | `999` | `8` |
| `max_losing_trades_day` | `999` | `3` |
| `max_losing_trades_session` | missing | `2` |
| `loss_streak_cooldown_min` | missing | `30` |
| `min_reentry_wait_min` | missing | `10` |
| `breakeven_enabled` | missing | `True` |
| `signal_threshold` | missing | `4` |

### 3.2 — Force-sync for 7 safety-critical keys

`ensure_persistent_settings()` now maintains a `_FORCE_SYNC_KEYS` set:

```python
_FORCE_SYNC_KEYS = {
    'max_losing_trades_day',
    'max_losing_trades_session',
    'max_trades_day',
    'loss_streak_cooldown_min',
    'min_reentry_wait_min',
    'breakeven_enabled',
    'signal_threshold',
}
```

On every deploy, each key in this set is compared against the bundled
`settings.json` value. If the volume's value differs, it is overwritten.
This is the same mechanism already used for `bot_name` — extended to all
safety-critical risk controls.

**Effect:** The next Railway deploy automatically corrects stale 999 values
to the bundled defaults. No manual volume file edits required.

---

## 4. Files changed

| File | Change |
|---|---|
| `config_loader.py` | 999 fallbacks replaced; `_FORCE_SYNC_KEYS` force-sync added; missing safety keys added to both boot paths |
| `version.py` | `__version__` → `"2.7.1"` |
| `bot.py` | Docstring updated to v2.7.1 |
| `settings.json.example` | Restored (was missing from v2.7 package); comment updated to v2.7.1 |
| `README.md` | Header → v2.7.1; v2.7.1 hotfix changelog added |
| `CONFLUENCE_READY.md` | v2.7.1 release notes prepended |

---

## 5. Upgrade checklist

1. Deploy the v2.7.1 zip (Railway redeploy)
2. Check Railway deploy logs for: `Updated N key(s) in persistent settings: ['max_losing_trades_day', ...]`
3. Confirm startup Telegram shows `Max losses/day: 3` (not 999)
4. No manual volume edits required — the force-sync handles it automatically

---

# GOLD v2.7 — Release Notes

**Date:** 2026-03-20
**Version:** v2.7
**Status:** Safety guards + Telegram accuracy + docstring corrections

---

## 1. Purpose

Three targeted safety improvements, two Telegram accuracy fixes, and a
documentation clean-up. No changes to CPR strategy, signal scoring, session
windows, or SL/TP logic.

---

## 2. Changes (v2.7)

### 2.1 — Dead-zone second-line guard (`bot.py` — `_execution_phase`)

Added `is_dead_zone_time(now_sgt)` as the very first check in `_execution_phase()`,
before any order is placed. Belt-and-suspenders against two known edge cases:

- **Startup reconcile race:** on container restart, `startup_oanda_reconcile()`
  stamps `now_sgt` as the recovered trade's timestamp. If the restart happens
  just after 01:00 SGT, the subsequent cycle could attempt a new entry because
  the primary guard in `_guard_phase()` had already passed.
- **00:59 → 01:00 boundary race:** a cycle that fires at 00:57 SGT and places
  an order filled after 01:00 SGT.

If triggered, logs at WARNING with event code `DEAD_ZONE_SKIP` and skips the
cycle cleanly. Status written to runtime state: `SKIPPED_DEAD_ZONE_EXEC`.

### 2.2 — Minimum inter-trade wait (`bot.py`)

New helper: `min_reentry_blocked_until(history, today_str, now_sgt, settings)`

Enforces a minimum pause between any two consecutive trades, independent of
the loss-streak cooldown. Reads `min_reentry_wait_min` (default `10` minutes).
Wired into `_guard_phase()` immediately after the cooldown block.

| Behaviour | Detail |
|---|---|
| Block active | Returns `(blocked_until: datetime, minutes_remaining: int)` |
| No block | Returns `(None, 0)` |
| Disabled | Set `min_reentry_wait_min: 0` |

When blocked: a single Telegram alert fires via `send_once_per_state()` (no
repeat every 5 min). Log event: `[REENTRY_WAIT]`. DB cycle status:
`SKIPPED_REENTRY_WAIT`.

**Impact on 2026-03-19 session:** 6 trades had gaps < 10 min. Of those, 5 were
losses and 1 was a win. Net guard benefit: approximately +$26 on that day.

New setting: `min_reentry_wait_min` (default `10`, set `0` to disable)

### 2.3 — Startup Telegram "Caps: off" corrected (`telegram_templates.py`, `scheduler.py`)

`msg_startup()` previously hardcoded `Caps: off` regardless of live configuration.

**Before:**
```
Caps:      off
```

**After:**
```
Caps:
  Max losses/day:     3
  Max losses/session: 2
  Loss cooldown:      30 min
  Min re-entry wait:  10 min
  Break-even:         on
```

`msg_startup()` now accepts five new parameters: `max_losing_trades_day`,
`max_losing_trades_session`, `loss_streak_cooldown_min`, `min_reentry_wait_min`,
`breakeven_enabled`. The `scheduler.py` call passes all five from the live
settings dict.

### 2.4 — Version string double-stamp fixed (`version.py`)

`BOT_NAME` was `"CPR Gold Bot v2.6"`. Scheduler composing
`f"{BOT_NAME} v{__version__}"` produced `"CPR Gold Bot v2.6 v2.6"` in the
startup Telegram. Fixed: `BOT_NAME = "CPR Gold Bot"`. Startup message now
correctly shows `"CPR Gold Bot v2.7"`.

### 2.5 — `settings.json.example` restored; `settings.json` excluded from package

`settings.json.example` was missing from the v2.6 zip entirely. Restored with
all production-safe defaults. `settings.json` (live config) is no longer
shipped in the archive — the zip is now built via Python `zipfile` which
explicitly excludes it, making the `.gitignore` enforcement zip-proof.

### 2.6 — Stale docstring corrected (`bot.py`)

| Line | Before | After |
|---|---|---|
| 5 | `breakeven_enabled: false` — SL is fixed at entry | `breakeven_enabled: true` — SL moves to entry after $5 profit |
| 12 | `score < 3 → no trade` | `score < 4 → no trade (MIN_TRADE_SCORE = 4)` |

---

## 3. Files changed

| File | Change |
|---|---|
| `bot.py` | Dead-zone exec guard in `_execution_phase`; `min_reentry_blocked_until()` helper; reentry wait check in `_guard_phase`; `min_reentry_wait_min` default in `validate_settings`; docstring corrected |
| `telegram_templates.py` | `msg_startup()` accepts and displays real cap values |
| `scheduler.py` | `msg_startup` call passes all 5 cap settings |
| `version.py` | `__version__` → `"2.7"`; `BOT_NAME` version suffix removed |
| `settings.json` | `_comment` updated to v2.7; all guard values confirmed correct |
| `settings.json.example` | Restored; all production-safe defaults; v2.7 reference |
| `README.md` | Header → v2.7; breakeven note corrected; v2.7 changelog added |
| `CONFLUENCE_READY.md` | v2.7 release notes prepended |

---

## 4. Settings reference (new keys in v2.7)

| Key | Default | Description |
|---|---|---|
| `min_reentry_wait_min` | `10` | Min minutes to wait after any trade close before next entry. Set `0` to disable. |

All other settings unchanged from v2.6.

---

## 5. Upgrade checklist

1. Deploy the v2.7 zip (Railway redeploy)
2. Copy `settings.json.example` → `settings.json` on the volume if starting fresh
3. Confirm startup Telegram shows `CPR Gold Bot v2.7` (not `v2.7 v2.7`)
4. Confirm startup Telegram shows real cap values (not `Caps: off`)
5. Confirm `[REENTRY_WAIT]` appears in logs after any trade close within 10 min
6. No data migration required — `trade_history.json`, `ops_state.json`,
   `runtime_state.json` all compatible

---

# GOLD v2.6 — Release Notes

**Date:** 2026-03-19
**Version:** v2.6
**Status:** Cap removal + config hardening

---

## 1. Purpose

All trading caps removed to allow unrestricted session trading. Hardcoded fallback
defaults in `config_loader.py` fixed to prevent old caps reappearing on fresh
Railway volume deployments. Cap references removed from Telegram startup and
session-open messages. No strategy or scoring changes.

---

## 2. Changes (v2.6)

| File | Change |
|---|---|
| `settings.json` | All caps set to 999 (off); cooldown set to 0 (disabled); bot_name bumped to v2.6 |
| `config_loader.py` | `setdefault` fallbacks for `max_trades_day` and `max_losing_trades_day` changed from 8/3 to 999 |
| `telegram_templates.py` | Startup message: removed per-session cap numbers and daily loss cap line; added `Caps: off`. Session open: removed cap line |
| `scheduler.py` | Removed cap params from `msg_startup()` call |
| `version.py` | Bumped to `2.6` |
| `README.md` | v2.6 changelog added |
| `CONFLUENCE_READY.md` | Updated to v2.6 |

---

## 3. Previous Release (v2.5)

### 2.1 — 08:00 SGT trading-day boundary (`bot.py`)

The trading day now resets at **08:00 SGT** instead of calendar midnight.
Any trade before 08:00 SGT counts against the *previous* day's cap, preventing
overnight losses from blocking the incoming London session.

New helper: `get_trading_day(now_sgt, day_start_hour=8)`
New setting: `trading_day_start_hour_sgt` (default `8`)

### 2.2 — Per-session loss sub-cap (`bot.py`, `telegram_templates.py`)

Each session (London / US) now has a 2-loss sub-cap (`max_losing_trades_session`).
When a session hits its limit it pauses while the 3-loss daily hard stop still
accumulates. A new `msg_session_cap()` Telegram alert fires on sub-cap hit,
showing session losses, remaining day losses, and the next session name.

New setting: `max_losing_trades_session` (default `2`)

| Scenario | Session | Day cap | Bot behaviour |
|---|---|---|---|
| 2 losses in London | Paused | 2/3 used | US can still trade |
| 2 losses in US | Paused | 2/3 used | Next day fresh |
| 3rd loss any session | — | 3/3 hit | Full day stop |

### 2.3 — Signal threshold raised to 4 (`bot.py`, `signals.py`, `settings.json`)

`signal_threshold` raised from 3 to **4**. Score-3 trades were net negative in
live data (weak SMA alignment or wide CPR). Score 3 is now blocked entirely.

**Bug fixed:** `signal_threshold` was stored in `ctx` but never compared against
score in `_signal_phase()`. Explicit gate added — this was a silent no-op before v2.4.

`MIN_TRADE_SCORE` in `signals.py` updated to 4.

### 2.4 — Trend exhaustion penalty (`signals.py`, `settings.json`)

New 4th scoring component. If `abs(price − SMA20) / ATR(14) > exhaustion_atr_mult`
(default 2.0), score is reduced by 1. Prevents entries at the exhaustion point of a move.

| Before | After |
|---|---|
| Score 4 at 2.5× stretch → entry | Score 3 → **blocked** (below threshold 4) |
| Score 5 at 2.5× stretch → entry | Score 4 → **partial** entry |
| Score 6 below threshold → full entry | Unchanged |

New setting: `exhaustion_atr_mult` (default `2.0`, set `0` to disable)

### 2.5 — Daily report moved to 15:30 SGT (`scheduler.py`)

Report fires at **15:30 SGT** (30 min before London open), replacing 09:30 SGT.
You receive yesterday's performance summary just before trading begins.

### 2.6 — Alert enrichments (`telegram_templates.py`)

| Alert | What was added |
|---|---|
| `msg_daily_cap()` | Trading window `16:00 → 01:00 SGT` + exact reset timestamp |
| `msg_cooldown_started()` | Current session name + remaining day losses |
| `msg_startup()` | `Window: 16:00 → 01:00 SGT` + `Day reset: 08:00 SGT` |
| `msg_new_day_resume()` | `Day reset: 08:00 SGT` line |
| `msg_session_cap()` | **New** — fires when a session sub-cap is hit |

### 2.7 — Duplicate alerts on fresh deployment fixed (`bot.py`)

**Problem:** On every brand-new deployment `ops_state.json` on the Railway
volume starts empty. All dedup keys are blank, so `send_once_per_state()`
re-fires every operational alert — even when the daily cap was already hit
or a cooldown was already active before the restart. This produced a blast of
🛑 Daily Cap and 🧊 Cooldown messages on every redeploy.

**Fix:** Added `_reconcile_ops_state()`, called at the top of every cycle
immediately after loading `ops_state.json`. It checks actual live conditions:

- If `daily_losses >= max_losing_trades_day` → pre-seeds `loss_cap_state`
- If an active cooldown exists in `runtime_state.json` → pre-seeds `cooldown_started_state`

No Telegram messages are sent. The function is a pure silent warm-up that
makes the dedup system deployment-proof.

Also removed both `ops.pop("cooldown_started_state")` calls from the loss-cap
return paths — these were wiping the dedup key each time the cap fired,
allowing the Cooldown alert to re-fire on the very next cycle.

### 2.8 — CPR levels always fetched live, cache removed (`signals.py`)

**Problem:** `cpr_cache.json` persisted on the Railway `/data` volume across
deployments. A mid-day redeploy left yesterday's CPR levels in the cache,
causing the bot to run the entire subsequent session on wrong pivot/support/
resistance levels.

**Fix:** Cache removed entirely. Every cycle now:
1. Fetches the previous day's OANDA daily candle directly
2. Computes CPR levels from scratch (pivot, TC, BC, R1, R2, S1, S2)
3. Runs `_validate_cpr_levels()` on the fresh result

`cpr_cache.json` on the volume can be safely deleted — it is no longer read
or written. Removed unused imports: `load_json`, `save_json`, `DATA_DIR`, `_dt`.

---

## 3. Settings reference (new / changed keys)

| Key | Default | Description |
|---|---|---|
| `signal_threshold` | `4` | Minimum score to trade (raised from 3) |
| `trading_day_start_hour_sgt` | `8` | Hour (SGT) when daily cap counter resets |
| `max_losing_trades_session` | `2` | Max losses per session before it pauses |
| `exhaustion_atr_mult` | `2.0` | ATR stretch threshold for exhaustion penalty |

**Removed:** `max_trades_asian`, `max_trades_main`
(replaced by `max_trades_london` and `max_trades_us` in v2.3)

> **Note:** Asian session is disabled in v2.4 — `session_thresholds` and `spread_limits` no longer include an `Asian` key. XAU/USD volatility during Asian hours is insufficient for reliable CPR breakouts.

---

## 4. Files changed

| File | Change |
|---|---|
| `bot.py` | Fix 1: removed `ops.pop("cooldown_started_state")` calls; Fix 4: added `_reconcile_ops_state()` + call in `_guard_phase()` |
| `signals.py` | Fix 2: TC/BC inversion normalised in-place; Fix 5: CPR cache removed, always-fetch logic, unused imports removed |
| `oanda_trader.py` | Fix 3: `place_order()` returns `sl_price`/`tp_price` |
| `version.py` | Bumped to `2.5` |
| `settings.json` | — |
| `settings.json.example` | — |
| `README.md` | Updated data directory listing, section 13, v2.5 changelog |
| `CONFLUENCE_READY.md` | This document |

## 5. Upgrade checklist

1. Deploy the new zip (Railway redeploy)
2. **Delete from `/data` volume** (if present):
   - `ops_state.json` — will be cleanly re-seeded by `_reconcile_ops_state()`
   - `cpr_cache.json` — no longer used; stale data
3. Confirm startup Telegram arrives with no duplicate cap/cooldown messages
4. In logs, confirm every cycle shows `CPR levels fetched | pivot=...` (never "loaded from cache")
5. On next redeploy mid-day: confirm no alert blast even if cap/cooldown was active

---

# GOLD v2.2 — Release Notes

**Date:** 2026-03-18
**Version:** v2.2
**Status:** Technical fix release — 8 bugs backported from v3.5 (no strategy changes)

---

## 1. Purpose

Backport of all technical/operational bug fixes from v3.5 into the v2.x
lineage. CPR strategy, signal scoring, session windows, SL/TP logic, and all
trading behaviour are completely unchanged.

---

## 2. Fixes

### 2.1 Version string correct on every deploy (`version.py`, `settings.json`)
`__version__` bumped to `"2.2"`. `bot_name` set to `"CPR Gold Bot v2.2"`.

### 2.2 `bot_name` auto-syncs on redeploy (`config_loader.py`)
`ensure_persistent_settings()` now compares `bot_name` from the bundled
defaults against the volume copy and overwrites it when they differ. All
other user-editable settings remain untouched.

### 2.3 Loss cap overshoot fixed (`bot.py` — `daily_totals()`)
When `trader` is supplied, an open position with negative unrealized P&L is
now counted as a loss immediately, preventing the 4/3 overshoot.

### 2.4 Repeated Telegram alerts fixed (`bot.py` — `send_once_per_state()`)
Each alert type now has its own dedicated ops_state key, eliminating the
key-collision that caused messages to re-fire every 5 minutes.

| Alert | Old key | New key |
|---|---|---|
| Loss cap | `ops_state` | `loss_cap_state` |
| Trade cap | `ops_state` | `trade_cap_state` |
| Cooldown started | `ops_state` | `cooldown_started_state` |
| Cooldown guard | `ops_state` | `cooldown_guard_state` |
| Window cap | `ops_state` | `window_cap_state` |
| Open trade cap | `ops_state` | `open_cap_state` |
| Spread | `ops_state` | `spread_state` |

### 2.5 Loss cap / cooldown message ordering (`bot.py` — `_guard_phase()`)
Early loss cap check added before `cooldown_started` notification. The
misleading "Resumes HH:MM SGT" message is never sent when the daily cap
has already been hit.

### 2.6 CPR cache validation (`signals.py`)
`_validate_cpr_levels()` added — 8 structural checks on every cache hit.
Failure → discard + re-fetch. Fresh fetches logged at INFO level.

### 2.7 Startup OANDA reconciliation (`oanda_trader.py`, `reconcile_state.py`, `bot.py`)
`startup_oanda_reconcile()` runs once per process start. Fetches today's
closing ORDER_FILLs from OANDA and injects missing records into history
before the first cycle, making the loss cap deployment-proof.

### 2.8 Enhanced reports (`reporting.py`, `telegram_templates.py`)
Profit factor, best trade (PnL + time), and worst trade added to daily,
weekly, and monthly Telegram reports.

---

## 3. Files changed

| File | Change |
|---|---|
| `version.py` | `"2.1"` → `"2.2"` |
| `settings.json` | `bot_name` → `"CPR Gold Bot v2.2"` |
| `config_loader.py` | `bot_name` auto-sync on redeploy |
| `bot.py` | Fixes 3, 4, 5, 7; version refs bumped |
| `signals.py` | `_validate_cpr_levels()`; cache validation; INFO log; version bumped |
| `oanda_trader.py` | `get_today_closed_transactions()` added |
| `reconcile_state.py` | `startup_oanda_reconcile()` added |
| `reporting.py` | `_stats()` extended with `best_trade`, `worst_trade` |
| `telegram_templates.py` | Daily/weekly/monthly reports updated; version bumped |
| `telegram_alert.py` | Version ref updated to v2.2 |
| `README.md` | v2.2 changelog entry added |
| `CONFLUENCE_READY.md` | v2.2 release notes section added |

---

## 4. Upgrade checklist

1. Deploy v2.2 (Railway redeploy)
2. Confirm startup Telegram shows `🥇 CPR Gold Bot v2.2`
3. Confirm `config_loader` log shows `Updated 1 key(s): ['bot_name']`
4. Check logs for `startup_oanda_reconcile complete: injected=N backfilled=N`
5. No settings migration required

---

# GOLD v2.1 — Release Notes

**Date:** 2026-03-18
**Version:** v2.1
**Status:** Bug-fix + hardening release

---

## 1. Purpose

This release fixes two critical runtime bugs that caused silent failures in
production, corrects five logic defects that made configuration settings
ineffective, and applies targeted code-quality improvements.

No changes were made to the CPR strategy, session windows, or SL/TP logic.

---

## 2. Critical bug fixes

### 2.1 Trade-closed alerts never sent (`backfill_pnl`)

**Severity:** Critical — silent data loss

**Root cause:**
`backfill_pnl` referenced `alert` and `settings` as though they were global
variables. Neither exists at module scope. Python's `try/except` around the
`alert.send(...)` call caught the resulting `NameError` silently and logged it
only as a warning. Every trade-closed Telegram alert was dropped.

**Fix:**
`alert` and `settings` are now explicit function parameters. The call site in
`run_bot_cycle` was updated to pass both.

A nested `from datetime import datetime as _dt` inside the loop body was also
removed; the module-level `datetime` import is used instead.

**Impact:**
Trade-closed notifications now fire correctly. The `closed_alert_sent` flag
(see §2.6) prevents a duplicate alert if reconciliation also detects the same
closed trade.

---

### 2.2 Bot crash on every order failure (`msg_order_failed`)

**Severity:** Critical — cycle crash at worst possible moment

**Root cause:**
`msg_order_failed` in `telegram_templates.py` accepted four positional
arguments: `(direction, instrument, units, error)`. The call site in
`bot.py` passed three additional keyword arguments — `free_margin`,
`required_margin`, `retry_attempted` — that the function signature did not
accept. Python raised `TypeError` on every failed order. This error was
**not** inside a `try/except`, so the entire bot cycle crashed.

**Fix:**
`msg_order_failed` now accepts and formats all three extra fields:

```
free_margin: float | None = None
required_margin: float | None = None
retry_attempted: bool = False
```

The message body now shows margin context and retry status, making order
failure alerts actionable.

---

## 3. Logic fixes

### 3.1 Medium-high news events silently ignored

**Root cause:**
`calendar_fetcher.py` accepts impact values `high`, `3`, `red`, and
`medium-high` and stores them with `impact = "high"`. However,
`news_filter.classify_event()` only matched `{"high", "3", "red"}`. Any event
arriving in the Forex Factory feed with `medium-high` impact was stored in the
cache but immediately dropped by the filter. Medium-event score penalties
never fired.

**Fix:**
Added `"medium-high"` to the accepted set in `news_filter.classify_event()`.

---

### 3.2 Position sizes ignored from settings

**Root cause:**
`signals.py` contained hardcoded `_SIZE_TIERS = [(4, 100), (2, 66)]`.
`score_to_position_usd()` read from these constants, completely ignoring
`position_full_usd` and `position_partial_usd` in `settings.json`. Changing
those values in configuration had no effect on actual order sizing.

**Fix:**
`score_to_position_usd(score, settings)` now reads from settings:

```python
full    = int(settings.get("position_full_usd", 100))
partial = int(settings.get("position_partial_usd", 66))
```

`SignalEngine.analyze()` now accepts a `settings` dict and passes it through.
The call site in `bot.py` passes the live settings.

---

### 3.3 Settings file overwritten on every read

**Root cause:**
`config_loader.load_settings()` called `_write_json(SETTINGS_FILE, settings)`
unconditionally at the end of every call. `load_settings` is called 2–3 times
per cycle. This meant any live edit to `DATA_DIR/settings.json` was silently
overwritten on the next cycle.

**Fix:**
The file is now only written back when `setdefault` has injected at least one
new key (i.e. the file was missing a default). No-op reads do not touch the
file.

---

### 3.4 Duplicate `setdefault` and missing defaults in `validate_settings`

**Root cause:**
`bot.py validate_settings()` called `setdefault("position_partial_usd", 66)`
twice (copy-paste error). The second call was dead code. More importantly,
`position_full_usd` had no `setdefault` at all, meaning it was used without
a fallback validation. The `enabled` key also had no default.

**Fix:**
Removed the duplicate. Added `setdefault` for both `position_full_usd` (100)
and `enabled` (True).

---

### 3.5 Environment variables lost to `secrets.json`

**Root cause:**
`load_secrets()` returned the entire contents of `secrets.json` if that file
existed, with no consideration of environment variables. In production on
Railway, environment variables are the intended source of truth. A developer
who tested locally with `secrets.json` and then committed it (by accident)
would silently have their production bot use the local credentials.

**Fix:**
Environment variables now always take priority:

```python
'OANDA_API_KEY': os.environ.get('OANDA_API_KEY') or file_secrets.get('OANDA_API_KEY', '')
```

`secrets.json` is kept as a developer convenience for local runs only.

---

### 3.6 Duplicate trade-closed Telegram alerts

**Root cause:**
`backfill_pnl` and `reconcile_state.reconcile_runtime_state` both independently
detect when a locally-FILLED trade has been closed at the broker and
back-fill `realized_pnl_usd`. Both ran in the same cycle. The first to run
would send `msg_trade_closed`; so could the second.

**Fix:**
`backfill_pnl` sets `trade["closed_alert_sent"] = True` after sending the
alert. `reconcile_state` only appends to `backfilled_trade_ids` (which
triggers the DB record) if `closed_alert_sent` is not already set. This
guarantees at-most-one alert per closed trade regardless of detection order.

---

### 3.7 `--last N` date filter used UTC on SGT timestamps

**Root cause:**
`analyze_trades.py` used `datetime.now()` (naive, local system time) as the
cutoff for `--last N days`. On Railway and most cloud platforms the system
timezone is UTC. Trade timestamps are stored in SGT (UTC+8). The mismatch
caused the filter to exclude trades from approximately the last 8 hours of the
window.

**Fix:**
Cutoff now uses `datetime.now(_SGT)` where `_SGT = pytz.timezone("Asia/Singapore")`.

---

## 4. Code quality improvements

| Item | Detail |
|------|--------|
| `import re` placement | Moved to module-level imports in `bot.py`; was placed mid-file after all other imports |
| Nested import in loop | `from datetime import datetime as _dt` removed from inside `backfill_pnl` loop body |
| Confusing third return value | `compute_sl_tp_prices` returned `tp_usd` as a third element that was already in scope at every call site; now returns `(sl_price, tp_price)` only |
| Hardcoded cycle interval | `msg_signal_update` footer "Next cycle in 5 min" now reads `cycle_minutes` from settings |
| `.gitignore` | Expanded to cover `__pycache__/`, `*.pyc`, `cpr_gold.db*`, `runtime_state.json`, `calendar_cache.json`, virtual environments, and editor artefacts |

---

## 5. Files changed

| File | Changes |
|------|---------|
| `bot.py` | Fix `backfill_pnl` signature and call site; fix duplicate/missing `setdefault`; fix `compute_sl_tp_prices` unpack; pass `settings` to `engine.analyze` and `score_to_position_usd`; add `cycle_minutes` to all `msg_signal_update` calls; move `import re` to top |
| `signals.py` | Remove hardcoded `_SIZE_TIERS`; `score_to_position_usd` reads from settings; `analyze()` accepts settings param |
| `telegram_templates.py` | `msg_order_failed` accepts and displays `free_margin`, `required_margin`, `retry_attempted`; `msg_signal_update` accepts `cycle_minutes` |
| `news_filter.py` | Add `"medium-high"` to accepted impact set in `classify_event` |
| `config_loader.py` | `load_settings` conditional write only; `load_secrets` env vars always win |
| `reconcile_state.py` | Guard `closed_alert_sent` before appending to `backfilled_trade_ids` |
| `analyze_trades.py` | SGT-aware datetime for `--last N` cutoff |
| `.gitignore` | Expanded exclusion list |
| `README.md` | Full rewrite for v2.0 |
| `CONFLUENCE_READY.md` | This document |

---

## 6. Configuration — no changes required

All default values are unchanged from v2.1. Existing `DATA_DIR/settings.json`
files will continue to work without modification.

The only observable behaviour change for operators is:

- Trade-closed Telegram alerts now arrive (they were silently dropped before)
- Order-failure Telegram alerts now include margin and retry detail
- Medium-high news events now correctly trigger score penalties
- `position_full_usd` and `position_partial_usd` in settings now take effect

---

## 7. Upgrade steps

1. Deploy the new code (Railway redeploy or `git pull` + restart)
2. No settings migration required
3. Confirm the startup Telegram message arrives
4. On next trade close, confirm the trade-closed alert arrives

---

## 8. Scope

**Included in this release:**
- All bug fixes listed in sections 2 and 3
- Code quality items in section 4
- Updated README and this document

**Not changed:**
- CPR scoring logic
- Session windows or thresholds
- SL/TP strategy
- Margin safety factor values
- OANDA API integration
- Database schema

---

## Changelog

### v2.1 — 2026-03-18

**Fix: TP fallback when R1/S1 structural level is too close**

Previously, if the R1 (for BUY) or S1 (for SELL) level was less than 0.50% from
entry, the trade was hard-blocked regardless of signal score. This caused valid
6/6 setups to be skipped.

**Resolution:** When R1/S1 < 0.50% from entry, the signal engine now falls back
to the fixed 0.75% TP (`fixed_pct_fallback`) instead of blocking the trade.
This preserves the intended 1:3 R:R and is consistent with the configured
`sl_pct`/`tp_pct` values in `settings.json`.

**File changed:** `signals.py` — TP selection block, `tp_source` label updated
to `fixed_pct_fallback` for logging visibility.

---

### v2.0 — 2026-03-18

**Production release — fixed SL / breakeven mover disabled / config hardening**

- `sl_mode` → `pct_based` (0.25% SL, 0.75% TP via `rr_ratio: 3.0`)
- `check_breakeven()` call disabled in `bot.py` (`breakeven_enabled: false`) — SL is fixed at 0.25% from entry and does not move. With a tight pct-based SL, moving to break-even adds operational complexity without meaningful risk reduction.
- `config_loader.py` hardened: all 6 required settings keys (`sl_mode`,
  `tp_mode`, `rr_ratio`, `max_trades_day`, `max_losing_trades_day`,
  `spread_limits`) now injected as safe defaults in `load_settings()` to
  prevent crash-loop on stale Railway persistent volume files

---

### v1.2 — 2026-03-18

**Hotfix — startup crash on Railway volume**

Settings validation raised `ValueError: Missing required settings keys` when
the persistent `/data/settings.json` was from an older deployment. Fixed by
merging new keys from the bundled defaults during `ensure_persistent_settings()`.

---

### v1.0 – v1.1

Initial release. CPR breakout signal engine, OANDA REST integration, session
guards, news filter, Telegram reporting, Railway deployment.
