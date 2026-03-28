"""Telegram message templates — CPR Gold Bot v3.8

Design philosophy:
  - Tier 1 (always send): startup, trade opened, trade closed, system error, daily cap
  - Tier 2 (send_once_per_state): session open, cooldown, direction block, gap filter,
    daily trend filter, post-TP cooldown, friday cutoff, new day resume
  - Removed: WATCHING messages when score < threshold, spread skip, outside session,
    re-entry wait every cycle, score breakdown checks on every cycle
"""
from __future__ import annotations

# SGT session schedule comment block (for documentation)
# 00:00 – 00:59   US Window (NY morning continuation)
# 01:00 – 15:59   Dead zone — no new entries
# 16:00 – 20:59   London Window (08:00–13:00 GMT)
# 21:00 – 23:59   US Window (13:00–16:00 EDT)

_DIV = "─" * 24


# ── helpers ───────────────────────────────────────────────────────────────────

def _mode(demo: bool) -> str:
    return "DEMO" if demo else "LIVE"

def _dir_icon(direction: str) -> str:
    return "🟢" if direction == "BUY" else "🔴"

def _outcome_icon(pnl: float) -> str:
    return "✅" if pnl > 0 else ("❌" if pnl < 0 else "➡️")

def _pnl_icon(pnl: float) -> str:
    return "🟢" if pnl > 0 else ("🔴" if pnl < 0 else "⚪")


# ── 1. Startup ────────────────────────────────────────────────────────────────

def msg_startup(
    version: str,
    mode: str,
    balance: float,
    min_score: int,
    cycle_minutes: int = 5,
    trading_day_start_hour: int = 8,
    max_losing_trades_day: int = 8,
    max_losing_trades_session: int = 4,
    loss_streak_cooldown_min: int = 30,
    min_reentry_wait_min: int = 5,
    breakeven_enabled: bool = False,
    max_trades_day: int = 20,
    max_trades_london: int = 10,
    max_trades_us: int = 10,
    position_partial_usd: int = 10,
    position_full_usd: int = 15,
    settings_ref: dict | None = None,
    post_tp_cooldown_min: int = 0,
    gap_filter_pct: float = 0,
    post_sl_direction_block_min: int = 0,
) -> str:
    _s = settings_ref or {}
    instrument = _s.get('instrument', 'XAU_USD').replace('_', '/')
    timeframe  = _s.get('timeframe', 'M15')
    threshold  = _s.get('signal_threshold', min_score)
    tf_filter  = _s.get('daily_trend_filter_enabled', False)
    london_end = _s.get('london_session_end', 20)
    us_end     = _s.get('us_session_end', 23)

    guards = []
    if gap_filter_pct > 0:
        guards.append(f"Gap filter: {gap_filter_pct:.1f}%")
    if post_tp_cooldown_min > 0:
        guards.append(f"Post-TP cooldown: {post_tp_cooldown_min} min")
    if post_sl_direction_block_min > 0:
        guards.append(f"Dir block (SL): {post_sl_direction_block_min} min")
    if tf_filter:
        guards.append("Daily trend filter: on")
    guard_lines = ("\n".join(f"  {g}" for g in guards) + "\n") if guards else ""

    return (
        f"🚀 Bot Started — CPR Gold Bot {version}\n{_DIV}\n"
        f"Mode:     {mode}\n"
        f"Balance:  ${balance:,.2f}\n"
        f"Pair:     {instrument} ({timeframe})\n"
        f"Score:    ≥{threshold}/6 · Sizes ${position_partial_usd} (4) | ${position_full_usd} (5–6)\n"
        f"{_DIV}\n"
        f"Sessions (SGT):\n"
        f"  🇬🇧 16:00–{london_end:02d}:59  London\n"
        f"  🗽 21:00–{us_end:02d}:59  US\n"
        f"  💤 01:00–15:59  Dead zone\n"
        f"{_DIV}\n"
        f"Caps:  {max_trades_day}/day · {max_trades_london}L/{max_trades_us}US · "
        f"{max_losing_trades_day} losses/day · {max_losing_trades_session}/session\n"
        f"Guards:\n{guard_lines}"
        f"Cycle: every {cycle_minutes} min ✅"
    )


# ── 2. Signal update (TRADE — score passed threshold) ─────────────────────────
# Only sent when score ≥ threshold AND a trade is about to fire (or blocked by guard)
# WATCHING messages when score < threshold are NOT sent

def msg_signal_update(
    banner: str,
    session: str,
    direction: str,
    score: int,
    position_usd: int,
    cpr_width_pct: float,
    detail_lines: list[str],
    news_penalty: int = 0,
    raw_score: int | None = None,
    decision: str = "WATCHING",
    reason: str = "",
    mandatory_checks: list | None = None,
    quality_checks: list | None = None,
    execution_checks: list | None = None,
    cycle_minutes: int = 5,
) -> str:
    # Only build a meaningful message — skip pure WATCHING noise
    if decision == "WATCHING" and score < 4:
        return ""   # caller checks for empty string and skips send
    dir_icon = _dir_icon(direction)
    score_str = f"{score}/6"
    if raw_score is not None and news_penalty:
        score_str += f" (raw {raw_score}, news {news_penalty:+d})"
    reason_line = f"  ⚠️ {reason}\n" if reason and decision != "TRADE" else ""
    return (
        f"📊 {decision} — {session}\n{_DIV}\n"
        f"{dir_icon} {direction}  Score {score_str}  ${position_usd} risk\n"
        f"CPR width: {cpr_width_pct:.2f}%\n"
        f"{reason_line}"
    )


# ── 3. Trade opened ───────────────────────────────────────────────────────────

def msg_trade_opened(
    banner: str,
    direction: str,
    setup: str,
    session: str,
    fill_price: float,
    signal_price: float,
    sl_price: float,
    tp_price: float,
    sl_usd: float,
    tp_usd: float,
    units: float,
    position_usd: int,
    rr_ratio: float,
    cpr_width_pct: float,
    spread_pips: int,
    score: int,
    balance: float,
    demo: bool,
    news_penalty: int = 0,
    raw_score: int | None = None,
    free_margin: float | None = None,
    required_margin: float | None = None,
    margin_mode: str = "NORMAL",
    margin_usage_pct: float | None = None,
) -> str:
    dir_icon  = _dir_icon(direction)
    score_str = f"{score}/6"
    if raw_score is not None and news_penalty:
        score_str += f" ({raw_score} raw, news {news_penalty:+d})"
    margin_line = (f"Margin: {margin_usage_pct:.0f}% used\n"
                   if margin_usage_pct is not None else "")
    retried = " ⚠️ RETRIED" if margin_mode == "RETRIED" else ""
    return (
        f"{dir_icon} Trade Opened — {_mode(demo)}\n{_DIV}\n"
        f"{direction}  {setup}  Score {score_str}\n"
        f"Entry:  ${fill_price:.2f}  ({session})\n"
        f"SL:     ${sl_price:.2f}  (−${sl_usd:.2f})\n"
        f"TP:     ${tp_price:.2f}  (+${tp_usd:.2f})\n"
        f"RR:     1:{rr_ratio:.2f}  ·  {units:.1f} units{retried}\n"
        f"{margin_line}"
        f"Bal:    ${balance:,.2f}"
    )


# ── 4. Breakeven ──────────────────────────────────────────────────────────────

def msg_breakeven(
    direction: str,
    entry: float,
    new_sl: float,
    profit_at_trigger: float,
    demo: bool,
) -> str:
    return (
        f"🔒 Breakeven Set — {_mode(demo)}\n{_DIV}\n"
        f"{direction}  Entry ${entry:.2f}\n"
        f"SL moved to entry (${new_sl:.2f})\n"
        f"Locked in: +${profit_at_trigger:.2f}"
    )


# ── 5. Trade closed ───────────────────────────────────────────────────────────

def msg_trade_closed(
    trade_id: str | int,
    direction: str,
    setup: str,
    entry: float,
    close_price: float,
    pnl: float,
    session: str,
    demo: bool,
    duration_str: str = "",
) -> str:
    icon    = _outcome_icon(pnl)
    outcome = "TP ✅" if pnl > 0 else ("SL ❌" if pnl < 0 else "BREAKEVEN")
    dur     = f"  {duration_str}" if duration_str else ""
    return (
        f"{icon} Trade Closed — {outcome}\n{_DIV}\n"
        f"{direction}  {setup}\n"
        f"${entry:.2f} → ${close_price:.2f}{dur}\n"
        f"P&L:  ${pnl:+.2f}  ({_mode(demo)})"
    )


# ── 6. News block ─────────────────────────────────────────────────────────────

def msg_news_block(
    event_name: str,
    event_time_sgt: str,
    window_min: int,
    direction: str,
) -> str:
    return (
        f"📰 News Block — {direction}\n{_DIV}\n"
        f"{event_name} at {event_time_sgt} SGT\n"
        f"±{window_min} min window · entries paused"
    )


# ── 7. News penalty ───────────────────────────────────────────────────────────

def msg_news_penalty(
    direction: str,
    score: int,
    raw_score: int,
    penalty: int,
    events: list[str],
    decision: str,
    reason: str,
) -> str:
    event_lines = "\n".join(f"  • {e}" for e in events[:3])
    return (
        f"📰 News Penalty — {direction}\n{_DIV}\n"
        f"Score: {raw_score}/6 → {score}/6 (−{penalty})\n"
        f"Events:\n{event_lines}\n"
        f"Decision: {decision}"
    )


# ── 8. Cooldown started ───────────────────────────────────────────────────────

def msg_cooldown_started(
    streak: int,
    cooldown_until_sgt: str,
    session_name: str = "",
    day_losses: int = 0,
    day_limit: int = 8,
) -> str:
    remaining = max(0, day_limit - day_losses)
    sess = f" · {session_name}" if session_name else ""
    return (
        f"🧊 Cooldown{sess}\n{_DIV}\n"
        f"{streak} consecutive losses\n"
        f"Paused until {cooldown_until_sgt} SGT\n"
        f"{day_losses}/{day_limit} daily losses used"
    )


# ── 9. Daily cap ──────────────────────────────────────────────────────────────

def msg_daily_cap(
    cap_type: str,
    count: int,
    limit: int,
    window: str = "",
    daily_pnl: float | None = None,
    session_name: str = "",
    last_loss_time_sgt: str = "",
    reset_time_sgt: str = "",
) -> str:
    labels = {
        "losing_trades": "Max losing trades",
        "total_trades":  "Max trades/day",
        "window_trades": f"Max trades ({window})",
    }
    label = labels.get(cap_type, "Cap reached")
    pnl_line = f"Day P&L:  ${daily_pnl:+.2f}\n" if daily_pnl is not None else ""
    reset_line = f"Resumes:  {reset_time_sgt} SGT\n" if reset_time_sgt else ""
    return (
        f"🔴 Daily Cap Reached\n{_DIV}\n"
        f"Type:     {label}\n"
        f"Count:    {count}/{limit}\n"
        f"{pnl_line}"
        f"{reset_line}"
        f"Action:   No new entries today"
    )


# ── 10. New day resume ────────────────────────────────────────────────────────

def msg_new_day_resume(
    today_str: str,
    balance: float,
    london_open_sgt: str = "16:00",
) -> str:
    return (
        f"🌅 New Day — {today_str}\n{_DIV}\n"
        f"Balance:  ${balance:,.2f}\n"
        f"Caps reset · London opens {london_open_sgt} SGT"
    )


# ── 11. Session cap ───────────────────────────────────────────────────────────

def msg_session_cap(
    session_name: str,
    session_losses: int,
    session_limit: int,
    day_losses: int,
    day_limit: int,
    next_session: str,
) -> str:
    icon = "🇬🇧" if "London" in session_name else "🗽"
    next_icon = "🗽" if "US" in next_session else "🇬🇧"
    remaining = max(0, day_limit - day_losses)
    return (
        f"{icon} Session Cap — {session_name}\n{_DIV}\n"
        f"{session_losses}/{session_limit} session losses\n"
        f"{day_losses}/{day_limit} daily losses  ({remaining} remaining)\n"
        f"Next: {next_icon} {next_session}"
    )


# ── 12. Session open ──────────────────────────────────────────────────────────

def msg_session_open(
    session_name: str,
    session_hours_sgt: str,
    trade_cap: int,
    trades_today: int,
    daily_pnl: float,
) -> str:
    icon = "🇬🇧" if "London" in session_name else "🗽"
    pnl_str = f"${daily_pnl:+.2f}" if trades_today > 0 else "—"
    return (
        f"{icon} {session_name} Open · {session_hours_sgt} SGT\n{_DIV}\n"
        f"Today: {trades_today} trade(s) · {pnl_str}\n"
        f"Cap: {trade_cap} trades this session"
    )


# ── 13. Spread too wide ───────────────────────────────────────────────────────
# Kept compact — spread blocks happen frequently, just a one-liner

def msg_spread_skip(
    spread_pips: int,
    limit_pips: int,
    session: str,
    direction: str,
) -> str:
    return (
        f"📶 Spread Skip — {direction}\n{_DIV}\n"
        f"Spread {spread_pips}p > limit {limit_pips}p ({session})"
    )


# ── 14. Order failed ─────────────────────────────────────────────────────────

def msg_order_failed(
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    reason: str,
    demo: bool,
) -> str:
    return (
        f"⚠️ Order Failed — {_mode(demo)}\n{_DIV}\n"
        f"{direction}  ${entry:.2f}\n"
        f"SL ${sl:.2f}  TP ${tp:.2f}\n"
        f"Reason: {reason}"
    )


# ── 15. Margin adjustment ─────────────────────────────────────────────────────

def msg_margin_adjustment(
    original_units: float,
    adjusted_units: float,
    original_risk_usd: float,
    adjusted_risk_usd: float,
    free_margin: float,
    margin_rate: float,
    direction: str,
    demo: bool,
) -> str:
    return (
        f"⚖️ Margin Adjusted — {_mode(demo)}\n{_DIV}\n"
        f"{direction}  {original_units:.1f}u → {adjusted_units:.1f}u\n"
        f"Risk ${original_risk_usd:.2f} → ${adjusted_risk_usd:.2f}\n"
        f"Free margin ${free_margin:,.2f}  Rate {margin_rate*100:.0f}%"
    )


# ── 16. System error ─────────────────────────────────────────────────────────

def msg_error(title: str, detail: str = "") -> str:
    detail_line = f"\nDetail:  {detail}" if detail else ""
    return (
        f"❌ System Error\n{_DIV}\n"
        f"Type:    {title}{detail_line}\n"
        f"Check logs for full trace"
    )


# ── 17. Friday cutoff ────────────────────────────────────────────────────────

def msg_friday_cutoff(cutoff_hour_sgt: int) -> str:
    return (
        f"🏁 Friday Cutoff — {cutoff_hour_sgt:02d}:00 SGT\n{_DIV}\n"
        f"No new entries until Monday 16:00 SGT"
    )


# ── 18. Daily report ─────────────────────────────────────────────────────────

def msg_daily_report(
    day_label: str,
    day_stats: dict,
    wtd_stats: dict,
    mtd_stats: dict,
    open_count: int,
    report_time: str,
    blocked_spread: int = 0,
    blocked_news: int = 0,
    blocked_signal: int = 0,
) -> str:
    def _stat_line(label, stats):
        if stats["count"] == 0:
            return f"{label}: No trades\n"
        wr = stats["win_rate"]
        return (
            f"{label}: {stats['count']} trades  "
            f"{stats['wins']}W/{stats['losses']}L  "
            f"WR {wr:.0f}%  ${stats['net_pnl']:+.2f}\n"
        )
    open_line = f"Open: {open_count} position(s)\n" if open_count else ""
    blocks = []
    if blocked_signal: blocks.append(f"{blocked_signal} signal")
    if blocked_news:   blocks.append(f"{blocked_news} news")
    if blocked_spread: blocks.append(f"{blocked_spread} spread")
    block_line = f"Blocked: {' · '.join(blocks)}\n" if blocks else ""
    return (
        f"📋 Daily Report — {day_label}\n{_DIV}\n"
        f"{_stat_line('Today', day_stats)}"
        f"{_stat_line('WTD', wtd_stats)}"
        f"{_stat_line('MTD', mtd_stats)}"
        f"{open_line}{block_line}"
        f"Report: {report_time} SGT"
    )


# ── 19. Weekly report ────────────────────────────────────────────────────────

def msg_weekly_report(
    week_label: str,
    week_stats: dict,
    mtd_stats: dict,
) -> str:
    if week_stats["count"] == 0:
        return f"📅 Weekly Report — {week_label}\n{_DIV}\nNo closed trades last week."
    wr = week_stats["win_rate"]
    avg_w = week_stats.get("avg_win", 0)
    avg_l = week_stats.get("avg_loss", 0)
    rr    = abs(avg_w/avg_l) if avg_l else 0
    return (
        f"📅 Weekly Report — {week_label}\n{_DIV}\n"
        f"Trades: {week_stats['count']}  "
        f"{week_stats['wins']}W/{week_stats['losses']}L  "
        f"WR {wr:.0f}%\n"
        f"Net P&L: ${week_stats['net_pnl']:+.2f}\n"
        f"Avg W: ${avg_w:+.2f}  Avg L: ${avg_l:+.2f}  RR 1:{rr:.2f}\n"
        f"{_DIV}\n"
        f"MTD: {mtd_stats['count']} trades  ${mtd_stats['net_pnl']:+.2f}"
    )


# ── 20. Monthly report ───────────────────────────────────────────────────────

def msg_monthly_report(
    month_label: str,
    month_stats: dict,
) -> str:
    if month_stats["count"] == 0:
        return f"📆 Monthly Report — {month_label}\n{_DIV}\nNo closed trades last month."
    wr    = month_stats["win_rate"]
    avg_w = month_stats.get("avg_win", 0)
    avg_l = month_stats.get("avg_loss", 0)
    rr    = abs(avg_w/avg_l) if avg_l else 0
    best  = month_stats.get("best_trade", 0)
    worst = month_stats.get("worst_trade", 0)
    return (
        f"📆 Monthly Report — {month_label}\n{_DIV}\n"
        f"Trades:  {month_stats['count']}  "
        f"{month_stats['wins']}W/{month_stats['losses']}L  "
        f"WR {wr:.0f}%\n"
        f"Net P&L: ${month_stats['net_pnl']:+.2f}\n"
        f"Avg W:   ${avg_w:+.2f}  Avg L: ${avg_l:+.2f}  RR 1:{rr:.2f}\n"
        f"Best:    ${best:+.2f}  Worst: ${worst:+.2f}"
    )
