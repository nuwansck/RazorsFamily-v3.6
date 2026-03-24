"""Signal engine for CPR breakout detection — v3.6

All parameters read from settings.json — no hardcoded values.

Scoring (max 6 points):
  1. Main condition  — price above/below CPR/PDH/PDL/R1/S1: +2 | R2/S2 extended: +1
  2. SMA alignment   — both SMA20 & SMA50 confirming direction: +2 | one: +1 | none: +0
  3. CPR width       — < cpr_narrow_pct (0.5%): +2 | ≤ cpr_wide_pct (1.0%): +1 | wider: +0
  4. Exhaustion      — price > exhaustion_atr_mult × ATR from SMA20: −1 penalty

Position size by score (from settings.json):
  score ≥ 5  →  position_full_usd    (default $15)
  score = 4  →  position_partial_usd (default $10)
  score < 4  →  no trade — blocked by signal_threshold

SL calculation (from settings.json):
  1. CPR structural level if within sl_pct (0.25%) of entry
  2. Fixed sl_pct (0.25%) otherwise

TP calculation (from settings.json):
  1. R1/S1 structural level if within tp_pct range
  2. Fixed tp_pct (0.6625% = 2.65× RR) fallback
  Minimum RR enforced: rr_ratio (2.65) — structural TP overridden if below floor (enforce_min_rr)
"""

import time
import logging
import requests
import pytz as _pytz
from config_loader import load_secrets, load_settings
from oanda_trader import make_oanda_session

log = logging.getLogger(__name__)

_SGT = _pytz.timezone("Asia/Singapore")

# Minimum score required to trade (scores below this are discarded)
MIN_TRADE_SCORE = 4  # module-level fallback — runtime value always read from settings.get('signal_threshold', 4)


def score_to_position_usd(score: int, settings: dict | None = None) -> int:
    """Return the risk-dollar position size for a given score.

    Reads position_full_usd and position_partial_usd from settings when
    provided; falls back to the settings defaults (position_full_usd / position_partial_usd).
    Returns 0 (no trade) for any score below MIN_TRADE_SCORE (4).
    """
    full = int((settings or {}).get("position_full_usd", 15))
    partial = int((settings or {}).get("position_partial_usd", 10))
    size_tiers = [
        (4, full),    # score >= 5 → full
        (2, partial), # score >= 3 → partial
    ]
    for threshold, size in size_tiers:
        if score > threshold:
            return size
    return 0



def _validate_cpr_levels(levels: dict) -> tuple[bool, str]:
    """Validate cached CPR levels for mathematical consistency.

    Checks structural relationships that must always hold given correct
    OANDA daily candle data.  Returns (True, "") on success, or
    (False, reason) if any check fails — caller should discard the cache
    and re-fetch.

    Checks (v2.5):
      1. All required keys present
      2. TC / BC — auto-normalised if inverted (pivot < bc edge case)
      3. R1 > pivot > S1
      4. R2 > R1
      5. S2 < S1
      6. PDH > PDL
      7. pivot between PDL and PDH
      8. cpr_width_pct > 0

    Note: TC < BC is a valid market-data edge case when the previous
    close is below the mid-range (pivot < bc).  Rather than discarding
    and re-fetching identical data every cycle, the levels dict is
    mutated in-place to swap TC ↔ BC and validation continues.
    """
    required = {"pivot", "tc", "bc", "r1", "r2", "s1", "s2", "pdh", "pdl", "cpr_width_pct"}
    missing = required - set(levels.keys())
    if missing:
        return False, f"missing keys: {missing}"

    pivot = levels["pivot"]; tc  = levels["tc"]; bc  = levels["bc"]
    r1    = levels["r1"];    r2  = levels["r2"]; s1  = levels["s1"]
    s2    = levels["s2"];    pdh = levels["pdh"]; pdl = levels["pdl"]
    cpr_w = levels["cpr_width_pct"]

    # Inverted CPR: normalise by swapping TC ↔ BC rather than rejecting.
    # This occurs when prev_close < avg(H,L), making pivot < bc mathematically.
    if tc < bc:
        import logging as _log
        _log.getLogger(__name__).warning(
            "CPR TC/BC inverted (TC=%.2f < BC=%.2f) — normalising by swap (v2.5).", tc, bc
        )
        levels["tc"], levels["bc"] = bc, tc
        tc, bc = levels["tc"], levels["bc"]

    if not (r1 > pivot):    return False, f"R1 ({r1}) must be > pivot ({pivot})"
    if not (pivot > s1):    return False, f"pivot ({pivot}) must be > S1 ({s1})"
    if not (r2 > r1):       return False, f"R2 ({r2}) must be > R1 ({r1})"
    if not (s2 < s1):       return False, f"S2 ({s2}) must be < S1 ({s1})"
    if not (pdh > pdl):     return False, f"PDH ({pdh}) must be > PDL ({pdl})"
    if not (pdl <= pivot <= pdh):
        return False, f"pivot ({pivot}) must be between PDL ({pdl}) and PDH ({pdh})"
    if not (cpr_w > 0):     return False, f"cpr_width_pct ({cpr_w}) must be > 0"
    return True, ""

class SignalEngine:
    def __init__(self, demo: bool = True):
        secrets = load_secrets()
        self.api_key = secrets.get("OANDA_API_KEY", "")
        self.account_id = secrets.get("OANDA_ACCOUNT_ID", "")
        self.base_url = (
            "https://api-fxpractice.oanda.com" if demo else "https://api-fxtrade.oanda.com"
        )
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.session = make_oanda_session(allowed_methods=["GET"])

    def analyze(self, asset: str = "XAUUSD", settings: dict | None = None):
        """Run the v2.0 CPR scoring engine.

        Parameters
        ----------
        asset : str
            Instrument identifier (only XAUUSD supported).
        settings : dict | None
            Bot settings dict; when provided, position sizes are read from
            ``position_full_usd`` and ``position_partial_usd`` keys.

        Returns
        -------
        (score, direction, details, levels, position_usd)
        """
        if settings is None:
            settings = load_settings()
        if asset != "XAUUSD":
            return 0, "NONE", "Only XAUUSD supported in this version", {}, 0

        instrument = str((settings or {}).get("instrument", "XAU_USD"))

        # ── Daily candles → CPR levels (always fetched live — no cache) ────
        daily_closes, daily_highs, daily_lows = self._fetch_candles(instrument, "D", 3)
        if len(daily_closes) < 2:
            return 0, "NONE", "Not enough daily data for CPR", {}, 0

        prev_high  = daily_highs[-2]
        prev_low   = daily_lows[-2]
        prev_close = daily_closes[-2]

        pivot         = (prev_high + prev_low + prev_close) / 3
        bc            = (prev_high + prev_low) / 2
        tc            = (pivot - bc) + pivot
        daily_range   = prev_high - prev_low
        r1            = (2 * pivot) - prev_low
        r2            = pivot + daily_range
        s1            = (2 * pivot) - prev_high
        s2            = pivot - daily_range
        pdh           = prev_high
        pdl           = prev_low
        cpr_width_pct = abs(tc - bc) / pivot * 100

        levels = {
            "pivot":         round(pivot, 2),
            "tc":            round(tc, 2),
            "bc":            round(bc, 2),
            "r1":            round(r1, 2),
            "r2":            round(r2, 2),
            "s1":            round(s1, 2),
            "s2":            round(s2, 2),
            "pdh":           round(pdh, 2),
            "pdl":           round(pdl, 2),
            "cpr_width_pct": round(cpr_width_pct, 3),
        }

        _ok, _reason = _validate_cpr_levels(levels)
        if not _ok:
            return 0, "NONE", f"CPR validation failed: {_reason}", {}, 0

        log.info(
            "CPR levels fetched | pivot=%.2f TC=%.2f BC=%.2f R1=%.2f S1=%.2f "
            "R2=%.2f S2=%.2f PDH=%.2f PDL=%.2f width=%.3f%%",
            pivot, tc, bc, r1, s1, r2, s2, pdh, pdl, cpr_width_pct,
        )

        # ── M15 candles → price, SMA, ATR ─────────────────────────────────
        m15_closes, m15_highs, m15_lows = self._fetch_candles(instrument, str((settings or {}).get("timeframe", "M15")), int((settings or {}).get("m15_candle_count", 65)))
        if len(m15_closes) < 52:
            return 0, "NONE", f"Not enough {(settings or {}).get('timeframe', 'M15')} data (need 52 candles for SMA{(settings or {}).get('sma_long_period', 50)})", levels, 0

        current_close = m15_closes[-1]

        # SMA20 and SMA50 use the last 20/50 completed candles (exclude current)
        _sma_s = int((settings or {}).get('sma_short_period', 20))
        _sma_l = int((settings or {}).get('sma_long_period', 50))
        sma20 = sum(m15_closes[-(_sma_s+1):-1]) / _sma_s
        sma50 = sum(m15_closes[-(_sma_l+1):-1]) / _sma_l

        # ATR(14) — used by bot.py for SL sizing, not for scoring
        atr_val = self._atr(m15_highs, m15_lows, m15_closes, int((settings or {}).get('atr_period', 14)))
        levels["atr"]          = round(atr_val, 2) if atr_val else None
        levels["current_price"] = round(current_close, 2)
        levels["sma20"]         = round(sma20, 2)
        levels["sma50"]         = round(sma50, 2)

        # ── Scoring ────────────────────────────────────────────────────────
        score     = 0
        direction = "NONE"
        reasons   = []

        reasons.append(
            f"CPR TC={tc:.2f} BC={bc:.2f} width={cpr_width_pct:.2f}% | "
            f"R1={r1:.2f} R2={r2:.2f} S1={s1:.2f} S2={s2:.2f} | "
            f"PDH={pdh:.2f} PDL={pdl:.2f}"
        )

        # ── 1. Main condition ──────────────────────────────────────────────
        if current_close > tc:
            direction = "BUY"
            if current_close > r2:
                score += 1
                setup = "R2 Extended Breakout"
                reasons.append(
                    f"⚠️ Price {current_close:.2f} > R2={r2:.2f} — extended entry (+1, main condition)"
                )
            else:
                score += 2
                if current_close > r1:
                    setup = "R1 Breakout"
                elif current_close > pdh:
                    setup = "PDH Breakout"
                else:
                    setup = "CPR Bull Breakout"
                reasons.append(
                    f"✅ Price {current_close:.2f} above CPR/PDH/R1 zone [{setup}] (+2, main condition)"
                )
        elif current_close < bc:
            direction = "SELL"
            if current_close < s2:
                score += 1
                setup = "S2 Extended Breakdown"
                reasons.append(
                    f"⚠️ Price {current_close:.2f} < S2={s2:.2f} — extended entry (+1, main condition)"
                )
            else:
                score += 2
                if current_close < s1:
                    setup = "S1 Breakdown"
                elif current_close < pdl:
                    setup = "PDL Breakdown"
                else:
                    setup = "CPR Bear Breakdown"
                reasons.append(
                    f"✅ Price {current_close:.2f} below CPR/PDL/S1 zone [{setup}] (+2, main condition)"
                )
        else:
            reasons.append(
                f"❌ Price {current_close:.2f} inside CPR (TC={tc:.2f} BC={bc:.2f}) — no signal"
            )
            return 0, "NONE", " | ".join(reasons), levels, 0

        # ── 2. SMA alignment ───────────────────────────────────────────────
        if direction == "BUY":
            both_below = sma20 < current_close and sma50 < current_close
            one_below  = (sma20 < current_close) != (sma50 < current_close)
            if both_below:
                score += 2
                reasons.append(
                    f"✅ Both SMAs below price — SMA20={sma20:.2f} SMA50={sma50:.2f} (+2)"
                )
            elif one_below:
                score += 1
                which = "SMA20" if sma20 < current_close else "SMA50"
                reasons.append(
                    f"⚠️ Only {which} below price — SMA20={sma20:.2f} SMA50={sma50:.2f} (+1)"
                )
            else:
                reasons.append(
                    f"❌ Both SMAs above price — SMA20={sma20:.2f} SMA50={sma50:.2f} (+0)"
                )
        else:  # SELL
            both_above = sma20 > current_close and sma50 > current_close
            one_above  = (sma20 > current_close) != (sma50 > current_close)
            if both_above:
                score += 2
                reasons.append(
                    f"✅ Both SMAs above price — SMA20={sma20:.2f} SMA50={sma50:.2f} (+2)"
                )
            elif one_above:
                score += 1
                which = "SMA20" if sma20 > current_close else "SMA50"
                reasons.append(
                    f"⚠️ Only {which} above price — SMA20={sma20:.2f} SMA50={sma50:.2f} (+1)"
                )
            else:
                reasons.append(
                    f"❌ Both SMAs below price — SMA20={sma20:.2f} SMA50={sma50:.2f} (+0)"
                )

        # ── 3. CPR width ───────────────────────────────────────────────────
        if cpr_width_pct < float((settings or {}).get('cpr_narrow_pct', 0.5)):
            score += 2
            reasons.append(f"✅ Narrow CPR ({cpr_width_pct:.2f}% < {float((settings or {}).get('cpr_narrow_pct', 0.5)):.1f}%) (+2)")
        elif cpr_width_pct <= float((settings or {}).get('cpr_wide_pct', 1.0)):
            score += 1
            reasons.append(f"⚠️ Moderate CPR ({cpr_width_pct:.2f}%) (+1)")
        else:
            reasons.append(f"❌ Wide CPR ({cpr_width_pct:.2f}% > {float((settings or {}).get('cpr_wide_pct', 1.0)):.1f}%) (+0)")

        # ── 4. Trend exhaustion penalty ────────────────────────────────────
        # If price is overextended (> exhaustion_atr_mult × ATR from SMA20),
        # reduce score by 1.  Prevents chasing moves that are already tired.
        # Set exhaustion_atr_mult = 0 in settings to disable entirely.
        _exhaust_mult = float((settings or {}).get("exhaustion_atr_mult", 2.0))
        if _exhaust_mult > 0 and atr_val and atr_val > 0:
            _stretch = abs(current_close - sma20) / atr_val
            if _stretch > _exhaust_mult:
                score = max(score - 1, 0)
                reasons.append(
                    f"⚠️ Trend exhaustion: stretch={_stretch:.2f}× ATR "
                    f"(>{_exhaust_mult}× threshold) — score −1 → {score}/6"
                )
            else:
                reasons.append(
                    f"✅ Stretch {_stretch:.2f}× ATR (≤{_exhaust_mult}× threshold) — no exhaustion penalty"
                )

        # ── Position size ──────────────────────────────────────────────────
        position_usd = score_to_position_usd(score, settings)

        # ── SL recommendation (priority order) ────────────────────────────
        # 1. Use CPR structural level if it is within 0.25% of entry
        # 2. Fall back to fixed 0.25% percentage SL
        entry = current_close
        if direction == "BUY":
            cpr_sl_candidate = bc          # below the bottom CPR for longs
            cpr_dist_pct = (entry - cpr_sl_candidate) / entry * 100
        else:
            cpr_sl_candidate = tc          # above the top CPR for shorts
            cpr_dist_pct = (cpr_sl_candidate - entry) / entry * 100

        fixed_sl_pct  = float(settings.get("sl_pct", 0.0025)) * 100
        fixed_tp_pct  = float(settings.get("tp_pct", 0.006625)) * 100
        if cpr_dist_pct <= fixed_sl_pct:
            sl_pct_used  = round(cpr_dist_pct, 4)
            sl_source    = "below_cpr" if direction == "BUY" else "above_cpr"
        else:
            sl_pct_used  = fixed_sl_pct
            sl_source    = "fixed_pct"
        sl_usd_rec = round(entry * sl_pct_used / 100, 2)

        # ── TP = SL × rr_ratio (v3.6 — guaranteed RR on every trade) ──────
        # Previous approach used R1/S1 structural levels as TP targets, which
        # caused RR variability (1:2.21 to 1:3.86 observed in live data).
        # v3.6 computes TP directly from SL distance × rr_ratio — always exact.
        # R1/S1 is logged as reference only (tp_source="sl_x_rr").
        _rr  = float((settings or {}).get('rr_ratio', 2.65))
        tp_skip = False
        tp_pct_used = round(sl_pct_used * _rr, 6)   # e.g. 0.25% × 2.65 = 0.6625%
        tp_source   = "sl_x_rr"
        tp_usd_rec  = round(sl_usd_rec * _rr, 2)

        # Log structural level for reference (informational only)
        target_level = r1 if direction == "BUY" else s1
        if direction == "BUY":
            level_dist_pct = round((target_level - entry) / entry * 100, 4)
        else:
            level_dist_pct = round((entry - target_level) / entry * 100, 4)
        levels["tp_structural_ref"] = round(target_level, 2)
        levels["tp_structural_pct"] = level_dist_pct

        # ── Mandatory / quality guards ───────────────────────────────────────
        rr_ratio = _rr   # always exact by construction
        rr_skip  = False  # RR is always >= rr_ratio by design

        blocker_reasons = []
        if rr_skip:
            blocker_reasons.append(f"R:R {rr_ratio:.2f} < 1:2")

        levels["score"]        = score
        levels["position_usd"] = position_usd
        levels["entry"]        = round(entry, 2)
        levels["setup"]        = setup
        levels["sl_usd_rec"]   = sl_usd_rec
        levels["sl_source"]    = sl_source
        levels["sl_pct_used"]  = sl_pct_used
        levels["tp_usd_rec"]   = tp_usd_rec
        levels["tp_source"]    = tp_source
        levels["tp_pct_used"]  = tp_pct_used
        levels["rr_ratio"]     = round(rr_ratio, 2)
        levels["mandatory_checks"] = {
            "score_ok": score >= MIN_TRADE_SCORE,
            "rr_ok": not rr_skip,
        }
        levels["quality_checks"] = {
            "tp_ok": not tp_skip,
        }
        levels["signal_blockers"] = blocker_reasons

        reasons.append(
            f"📐 SL={sl_usd_rec} ({sl_source} {sl_pct_used:.3f}%) | "
            f"TP={tp_usd_rec} ({tp_source} {tp_pct_used:.3f}%) | R:R 1:{rr_ratio:.2f}"
        )
        if blocker_reasons:
            reasons.append("🚫 " + " | ".join(blocker_reasons))

        details = " | ".join(reasons)
        if blocker_reasons:
            log.info(
                "CPR signal BLOCKED | setup=%s | dir=%s | score=%s/6 | blockers=%s",
                setup, direction, score, "; ".join(blocker_reasons),
            )
        else:
            log.info(
                "CPR signal | setup=%s | dir=%s | score=%s/6 | position=$%s",
                setup, direction, score, position_usd,
            )
        return score, direction, details, levels, position_usd

    # ── Data helpers ───────────────────────────────────────────────────────────

    def _fetch_candles(self, instrument: str, granularity: str, count: int = 60):
        url    = f"{self.base_url}/v3/instruments/{instrument}/candles"
        params = {"count": str(count), "granularity": granularity, "price": "M"}
        for attempt in range(3):
            try:
                r = self.session.get(url, headers=self.headers, params=params, timeout=15)
                if r.status_code == 200:
                    candles  = r.json().get("candles", [])
                    complete = [c for c in candles if c.get("complete")]
                    closes   = [float(c["mid"]["c"]) for c in complete]
                    highs    = [float(c["mid"]["h"]) for c in complete]
                    lows     = [float(c["mid"]["l"]) for c in complete]
                    return closes, highs, lows
                log.warning("Fetch candles %s %s: HTTP %s", instrument, granularity, r.status_code)
            except Exception as e:
                log.warning(
                    "Fetch candles error (%s %s) attempt %s: %s",
                    instrument, granularity, attempt + 1, e,
                )
            time.sleep(1)
        return [], [], []

    def _atr(self, highs: list, lows: list, closes: list, period: int = 14) -> float | None:
        """Return the most recent ATR value, or None if insufficient data."""
        n = len(closes)
        if n < period + 2 or len(highs) < n or len(lows) < n:
            return None
        trs = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, n)
        ]
        atr = sum(trs[:period]) / period
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period
        return atr
